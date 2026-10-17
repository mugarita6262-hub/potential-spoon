"""rakuten_room の CLI。ふだんはサーバーの webapp（スケジューラ）が同じ関数を呼ぶ。全体像は ARCHITECTURE.md。

使い方（サーバーで手動実行するとき）:
  python -m src.main login       初回だけ。ブラウザで楽天ROOMに手動ログイン
  python -m src.main prepare     ROOM: 今日の候補を選び、紹介文を作る
  python -m src.main post        ROOM: 下書きを投稿する
  python -m src.main run         ROOM: prepare（未準備なら）→ post
  python -m src.main status      ROOM: 今日の目標と投稿数
  python -m src.main like|follow|unfollow [--n N]   ROOM: いいね・フォロー・解除
  python -m src.main prune [--commit] [--max N]      ROOM: 古い投稿の削除
  python -m src.main sitedrop [--dry]  Threads: 買い時ナビの値下がり速報
  python -m src.main calendar    Threads: セール・お得日のお知らせ
  python -m src.main trivia      Threads: 買い物の比べ方の豆知識
  python -m src.main instagram   Instagram: 1件投稿
  python -m src.main site [--no-collect]   買い時ナビの価格収集とページ再生成
"""
from __future__ import annotations

import sys

import json
import os
from datetime import date

# コンソールの既定コードページ（Windowsのcp932等）だと絵文字（✅❌🎯など）の
# print()がUnicodeEncodeErrorで落ちるため、標準出力/エラーをUTF-8化しておく。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _today_iso() -> str:
    return date.today().isoformat()


def _room_slug(cfg: dict) -> str:
    import re
    m = re.search(r"/(room_[0-9a-z]+|[A-Za-z0-9_.-]+)/items", cfg.get("my_room_url", ""))
    return m.group(1) if m else ""


def _arg_int(args, flag: str, default: int) -> int:
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            try:
                return int(args[i + 1])
            except ValueError:
                pass
        if a.startswith(flag + "="):
            try:
                return int(a.split("=", 1)[1])
            except ValueError:
                pass
    return default

from .captions import (
    captions_path,
    load_captions,
    save_drafts,
    save_plan,
)
from .config import load_config
from .rakuten_api import RakutenAPI


def cmd_prepare(cfg: dict) -> None:
    from .sale_calendar import sale_status
    from .selector import select_items

    try:
        api = RakutenAPI(cfg["_app_id"], cfg["_access_key"], cfg["_affiliate_id"])
    except RuntimeError as exc:
        print(exc)
        return

    base_count = int(cfg.get("post_count", 10))
    items = select_items(cfg, api)  # candidate_pool 件（かぶり吸収 & セール判定用）
    if not items:
        print("条件を満たす候補が見つかりませんでした。config.yaml のしきい値を緩めてみてください。")
        return

    # セール・イベント判定 → その日の投稿目標数
    st = sale_status(cfg, items)
    target_count = max(base_count, round(base_count * st["multiplier"]))
    save_plan({
        "date": _today_iso(),
        "base_count": base_count,
        "multiplier": st["multiplier"],
        "target_count": target_count,
        "reasons": st["reasons"],
    })

    save_drafts(items)
    if st["reasons"]:
        print(f"\n🎯 セール検知: {' / '.join(st['reasons'])}")
        print(f"   今日の投稿目標: {base_count} → {target_count} 件")
    print("\n--- 選定結果 ---")
    for i, it in enumerate(items, 1):
        print(f"{i:2d}. [{it['score']}] {it['itemName'][:50]}  "
              f"{it['price']:,}円 レビュー{it['reviewCount']}")

    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        try:
            from .ai_captions import generate_captions

            caps = generate_captions(items)
            if caps:
                captions_path().write_text(
                    json.dumps(
                        [{"itemUrl": u, "caption": c} for u, c in caps.items()],
                        ensure_ascii=False, indent=2,
                    ),
                    encoding="utf-8",
                )
                print(f"キャプションを自動生成して保存しました: {captions_path()}")
                print("続けて `python -m src.main post` を実行できます。")
                return
            print("キャプション生成の結果が空でした。プロンプト方式に切り替えます。")
        except Exception as exc:  # noqa: BLE001
            print(f"キャプション自動生成に失敗しました（{exc}）。プロンプト方式に切り替えます。")

    print("紹介文を作れなかったので、今日の投稿は次の room_post で作り直します。")


def cmd_post(cfg: dict, dry_run: bool = False, serial: bool = False,
             full_day: bool = False) -> None:
    from .poster import post_drafts, post_drafts_tabs

    if serial or dry_run:
        post_drafts(cfg, dry_run=dry_run)
    else:
        post_drafts_tabs(cfg, full_day=full_day)


def cmd_login() -> None:
    from .poster import login

    login()


def cmd_status(cfg: dict) -> None:
    from .captions import captions_path, drafts_path, load_plan
    from .posted_log import posted_today

    plan = load_plan()
    base = int(cfg.get("post_count", 10))
    target = int(plan.get("target_count") or base)
    done = posted_today()
    print(f"日付           : {_today_iso()}")
    print(f"今日の準備     : {'済み' if drafts_path().exists() else 'まだ（① を実行）'}"
          + ("／紹介文あり" if captions_path().exists() else "／紹介文なし"))
    if plan.get("reasons"):
        print(f"セール判定     : {' / '.join(plan['reasons'])}  → 目標 {target} 件")
    else:
        print(f"投稿目標       : {target} 件")
    print(f"今日の投稿済み : {done} / {target} 件"
          + ("  ✅ 目標達成" if done >= target else f"  （あと {target - done} 件）"))
    print(f"1回の投稿数    : {cfg.get('post_batch_size', target)} 件")


def cmd_run(cfg: dict, full_day: bool = False) -> None:
    if load_captions():
        print("今日の準備は済んでいます（紹介文あり）。投稿タブを開きます。\n")
    else:
        cmd_prepare(cfg)
    if load_captions():
        cmd_post(cfg, full_day=full_day)
    else:
        print("\nキャプション待ちです。上の手順を済ませてから もう一度どうぞ。")


def _ensure_threads_ready(cfg: dict) -> bool:
    """Threadsトークンの存在確認＋自動延長＋1日の投稿数上限チェック。
    使えない/上限到達の場合はFalseを返す（呼び出し側は中断する）。

    sns/a8/digest/trend/calendar/triviaの6種が個別にスケジュールされているため、
    複数が同じ日にたまたま重なっても確実に1日の投稿数を抑えられるよう、
    ジョブごとの頻度ではなくここで全体の上限を一括管理する。
    """
    if not cfg.get("_threads_token") or not cfg.get("_threads_user_id"):
        print(".env の THREADS_ACCESS_TOKEN / THREADS_USER_ID が未設定です。"
              "SETUP_THREADS.md の手順で取得してください。")
        return False

    from .sns_posted_log import posted_today as _sns_posted_today

    max_per_day = int(cfg.get("posting_limits", {}).get("max_per_day", 5))
    done_today = _sns_posted_today("threads")
    if done_today >= max_per_day:
        print(f"  本日の投稿数が上限（{max_per_day}件）に達しているためスキップします"
              f"（本日 {done_today} 件）。")
        return False

    from .threads_poster import refresh_long_lived_token

    try:
        data = refresh_long_lived_token(cfg["_threads_token"])
        if data["access_token"] != cfg["_threads_token"]:
            from .config import update_env_value
            update_env_value("THREADS_ACCESS_TOKEN", data["access_token"])
            cfg["_threads_token"] = data["access_token"]
            print("  Threadsアクセストークンを延長しました。")
    except Exception as exc:  # noqa: BLE001
        print(f"  トークン延長に失敗（既存トークンで続行）: {exc}")
    return True


def _ensure_instagram_ready(cfg: dict) -> bool:
    """Instagramトークンの存在確認＋自動延長＋1日の投稿数上限チェック。

    Threads側の上限（posting_limits.max_per_day）とは別カウント
    （プラットフォームが違うので、それぞれ独立して数える）。
    """
    if not cfg.get("_instagram_token") or not cfg.get("_instagram_user_id"):
        print(".env の INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID が未設定です。")
        return False

    from .sns_posted_log import posted_today as _sns_posted_today

    max_per_day = int(cfg.get("posting_limits", {}).get("instagram_max_per_day", 1))
    done_today = _sns_posted_today("instagram")
    if done_today >= max_per_day:
        print(f"  本日のInstagram投稿数が上限（{max_per_day}件）に達しているためスキップします"
              f"（本日 {done_today} 件）。")
        return False

    from .instagram_poster import refresh_long_lived_token

    try:
        data = refresh_long_lived_token(cfg["_instagram_token"])
        if data["access_token"] != cfg["_instagram_token"]:
            from .config import update_env_value
            update_env_value("INSTAGRAM_ACCESS_TOKEN", data["access_token"])
            cfg["_instagram_token"] = data["access_token"]
            print("  Instagramアクセストークンを延長しました。")
    except Exception as exc:  # noqa: BLE001
        print(f"  トークン延長に失敗（既存トークンで続行）: {exc}")
    return True


def _post_to_threads_notified(cfg: dict, text: str, image_url: str | None = None) -> str:
    """post_to_threadsを呼び、成功したら「初動が肝心」の通知も送る。

    Threadsのアルゴリズムは投稿直後30〜60分の反応（いいね・リプライ）を見て
    「おすすめ」に載せるか判断するため、人が早めに反応する価値が大きい。
    ここだけは自動化できないので、せめて気づけるようにntfyで知らせる。
    """
    from .notify import notify
    from .threads_poster import post_to_threads

    post_id = post_to_threads(cfg["_threads_token"], cfg["_threads_user_id"],
                               text, image_url=image_url)
    from .recent_openings import record as record_opening

    record_opening(text)
    preview = text.split("\n", 1)[0][:40]
    notify(
        f"投稿しました: {preview}\n"
        "最初の30〜60分の反応が伸びを左右します。よければ今のうちに"
        "いいね・返信しておくと効果的です。",
        title="rakuten_room: posted, engage now",
    )
    return post_id


def _post_hook_then_reply(cfg: dict, hook: str, text: str, image_url: str | None = None,
                          record_base: dict | None = None,
                          category: str = "") -> tuple[str, str]:
    """商品を出さない普通の「フック投稿」を出し、リンク＋#PR付きの紹介投稿を続けて出す。
    (紹介投稿のID, 出し方) を返す。出し方は "reply"（ツリー。いわゆる「リンクはリプ欄」）と
    "quote"（フックを引用した通常投稿）を交互にする A/B テスト中（2026-10-03〜）。
    ツリーだとリンク投稿がフックの0.9%しか見られていないため、タイムラインに直接出る
    引用の方が見られるかを比べる。結果は insights の到達率で形式別に出る。

    全投稿が「#PR＋リンク」だと広告アカウントにしか見えず意味が無い、というユーザー判断で
    2026-09-30に変更。フック側は特定商品に触れない独立した話題なのでPR不要、商品を
    紹介する引用側に#PRを付ける（フック側で商品を紹介してPRを引用側だけに置く形は
    ステマ規制に抵触するので作らない）。フックも1投稿として記録し、1日の上限に数える。
    """
    import random
    import time as _time

    from .sns_posted_log import last_link_mode
    from .sns_posted_log import record_posted as sns_record_posted
    from .threads_poster import post_to_threads

    # 2026-10-08 A/Bテスト終了: ツリーのリンク投稿はフックの数%（0回の日も）しか見られず、
    # 引用は2〜3割に届いた。以後は引用に固定（config の sns.threads.link_mode で reply/ab に戻せる）
    lm = ((cfg.get("sns", {}) or {}).get("threads", {}) or {}).get("link_mode", "quote")
    if lm == "ab":
        mode = "quote" if last_link_mode() == "reply" else "reply"
    else:
        mode = "reply" if lm == "reply" else "quote"
    hook_id = _post_to_threads_notified(cfg, hook)
    if record_base is not None:
        sns_record_posted(
            {"itemCode": f"hook:{record_base.get('itemCode', '')}",
             "itemName": f"(フック) {record_base.get('itemName', '')[:40]}"},
            platform="threads", post_id=hook_id, category=category,
        )
    _time.sleep(random.uniform(40, 90))
    # 失敗しても通常投稿で出し直さない。応答がタイムアウトしただけで実は公開されていることがあり、
    # 出し直すと同じ内容が2つ出る（2026-09-30に実際に発生）。その回はフック投稿だけになる
    if mode == "quote":
        post_id = post_to_threads(cfg["_threads_token"], cfg["_threads_user_id"], text,
                                  image_url=image_url, quote_post_id=hook_id)
    else:
        post_id = post_to_threads(cfg["_threads_token"], cfg["_threads_user_id"], text,
                                  image_url=image_url, reply_to_id=hook_id)
    print(f"  リンク投稿の出し方: {'引用' if mode == 'quote' else 'ツリー（リプ欄）'}")
    return post_id, mode


def cmd_sitedrop(cfg: dict) -> None:
    """買い時ナビの「値下がり速報」をThreadsに出す（フック＋買い時ナビの値下がり欄へのリンク）。

    2026-10-18: Threadsを値下がり情報アカウントに一本化。時間帯・季節に合うジャンルを選び、
    ジャンル内で値下がりが多いペルソナに向けて書く（threads_deal）。フックはジャンル全体の
    数字だけ（商品名なし）、引用側に商品名と下げ幅の一覧（コードが正確に作る）＋リンク＋#PR。
    リンク先の値下がり欄は同じデータから作られるので、投稿で見た商品がそのまま並ぶ。
    """
    import json as _json
    from datetime import datetime as _dt

    from .content_captions import generate_dealdrop_caption
    from .price_history import load_all
    from .site_builder import GENRE_PERSONAS, GENRES, SITE_ITEMS_FILE, SITE_URL, _genre_ok, pick_key, rankings
    from .sns_posted_log import posted_today as sns_posted_today
    from .sns_posted_log import record_posted as sns_record_posted
    from .sns_posted_log import recently_posted_keys
    from .threads_deal import genre_score, pick_persona, post_name, slot_of

    sc = cfg.get("sitedrop", {}) or {}
    if not sc.get("enabled", True):
        print("sitedrop投稿は設定(sitedrop.enabled)で無効になっています。")
        return
    if not _ensure_threads_ready(cfg):
        return

    now = _dt.now()
    # 投稿の直前にサイトを作り直す。投稿の数字・商品と、リンク先の値下がり欄を同じデータにそろえるため
    from .site_builder import build as _build_site
    _build_site(None)
    data = _json.loads(SITE_ITEMS_FILE.read_text(encoding="utf-8"))
    hist = load_all()
    skip = recently_posted_keys(int(sc.get("repost_cooldown_days", 3)), platform="threads")
    cands = []
    for g in GENRES:
        if f"sitedrop:{g['slug']}" in skip:
            continue
        items = [it for it in data.get(g["slug"], []) if _genre_ok(g, it)]
        _, drops = rankings(items, hist)
        score = genre_score(g["slug"], len(drops), now)
        # 3割を超える下げが残るジャンルは、本物か選択肢の切り替わりか見分けがつかないので自動では出さない
        if len(drops) >= int(sc.get("min_drops", 2)) and score > 0 and max(d["drop_pct"] for d in drops) <= 30:
            cands.append((score, g, drops))
    if not cands:
        print("値下がりを紹介できるジャンルがありません（件数が少ないか、すべてクールダウン中）。")
        return
    cands.sort(key=lambda x: x[0], reverse=True)
    _, g, drops = cands[0]
    persona, target = pick_persona(g["slug"], drops, GENRE_PERSONAS)
    # フックの数字はジャンル全体（リンク先の値下がり欄と同じ数字）。ペルソナは呼びかけと一覧の絞り込みに使う
    n, max_pct = len(drops), max(d["drop_pct"] for d in drops)

    def _is_low(d: dict) -> bool:
        return d.get("days", 0) >= 7 and d["drop_pct"] >= 5 and d["price"] <= d.get("low", 0) and d.get("high", 0) >= d.get("low", 0) * 1.03

    n_low = sum(1 for d in drops if _is_low(d))
    slot = slot_of(now)
    print(f"今回の値下がり速報: {g['name']} / {persona or '全体'}（{n}件、最大{max_pct:.0f}%、最安{n_low}件、{slot}）")
    hook, caption = generate_dealdrop_caption(g["name"], persona, n, max_pct, n_low, slot)
    if not hook or not caption:
        print("紹介文の生成に失敗しました。")
        return

    picks = target[:3]
    lines = [f"・{post_name(d['itemName'])}（−{d['drop_pct']:.0f}%{'・記録' + str(d['days']) + '日で最安' if _is_low(d) else ''}）" for d in picks]
    url = (f"{SITE_URL}/{g['slug']}/?utm_source=threads&utm_medium=social&utm_campaign={g['slug']}-drops"
           f"&pick={'.'.join(pick_key(d) for d in picks)}#drops")
    hook = f"{hook}\n\n（値下がり中の商品は引用でまとめています・PR）"
    text = (f"PR｜{caption}\n\n" + "\n".join(lines) + f"\n\nいまの値段・ふだんの値段・値動きはここで見られます👇\n{url}\n"
            f"#{sc.get('disclosure') or 'PR'} #買い時ナビ")
    base = {"itemCode": f"sitedrop:{g['slug']}", "itemUrl": url, "itemName": f"{g['name']}の値下がり速報"}
    category = f"sitedrop:{g['name']}"
    if "--dry" in sys.argv:
        print("---- hook\n" + hook + "\n---- quote\n" + text)
        return
    try:
        post_id, mode = _post_hook_then_reply(cfg, hook, text, record_base=base, category=category)
        sns_record_posted(base, platform="threads", post_id=post_id, category=category, link_mode=mode)
        print(f"✅ Threads投稿完了（値下がり速報: {g['name']}） -> id={post_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 投稿失敗: {exc}")

    print(f"\n本日のThreads投稿累計 {sns_posted_today('threads')} 件")


def cmd_calendar(cfg: dict) -> None:
    """条件に依存しないネタ③: セール・お得日のリマインド（リンクなし・PR不要）。

    既存のsale_calendar.pyのイベント判定をそのまま流用する。
    """
    from datetime import date, timedelta

    from .content_captions import build_info_post_text, generate_calendar_caption
    from .sns_posted_log import posted_today as sns_posted_today
    from .sns_posted_log import record_posted as sns_record_posted
    from .sns_posted_log import recently_posted_keys

    cc = cfg.get("calendar", {}) or {}
    if not cc.get("enabled", True):
        print("calendar投稿は設定(calendar.enabled)で無効になっています。")
        return
    if not _ensure_threads_ready(cfg):
        return

    today = date.today()
    tomorrow = today + timedelta(days=1)

    event_name = None
    hint = None
    for e in (cfg.get("sale_boost", {}) or {}).get("manual_events", []) or []:
        try:
            start = date.fromisoformat(str(e["start"]))
            end = date.fromisoformat(str(e["end"]))
        except (KeyError, ValueError, TypeError):
            continue
        if today <= start <= tomorrow + timedelta(days=2):
            event_name = e.get("name", "セール")
            hint = f"{start.month}/{start.day}〜{end.month}/{end.day}"
            break

    if not event_name and tomorrow.day % 5 == 0:
        event_name = "5と0のつく日"
        hint = f"{tomorrow.month}月{tomorrow.day}日"

    if not event_name:
        print("今日・明日は特にお知らせできるイベントがありません。")
        return

    key = f"calendar:{event_name}:{tomorrow.isoformat()}"
    if key in recently_posted_keys(2, platform="threads"):
        print("このイベントは既に案内済みです。")
        return

    print(f"今回のcalendar: {event_name}（{hint}）")
    caption = generate_calendar_caption(event_name, hint)
    if not caption:
        print("告知文の生成に失敗しました。")
        return

    text = build_info_post_text(caption, tags="#楽天セール情報 #お得情報")
    try:
        post_id = _post_to_threads_notified(cfg, text)
        sns_record_posted(
            {"itemCode": key, "itemUrl": "", "itemName": event_name},
            platform="threads", post_id=post_id, category="calendar",
        )
        print(f"✅ Threads投稿完了（calendar: {event_name}） -> id={post_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 投稿失敗: {exc}")

    print(f"\n本日のThreads投稿累計 {sns_posted_today('threads')} 件")


def cmd_trivia(cfg: dict) -> None:
    """条件に依存しないネタ④: ミニ知識・あるあるネタ（リンクなし・PR不要）。

    値下がり・A8リンクなど外部データに一切依存しないので、4つの中で一番身軽。
    """
    import random

    from .content_captions import build_info_post_text, generate_trivia_caption
    from .sns_posted_log import posted_today as sns_posted_today
    from .sns_posted_log import record_posted as sns_record_posted
    from .sns_posted_log import recently_posted_keys

    tvc = cfg.get("trivia", {}) or {}
    if not tvc.get("enabled", True):
        print("trivia投稿は設定(trivia.enabled)で無効になっています。")
        return
    if not _ensure_threads_ready(cfg):
        return

    topics = list(tvc.get("topics", []) or [])
    if not topics:
        print("config.yaml の trivia.topics が空です。")
        return

    cooldown_days = int(tvc.get("repost_cooldown_days", 7))
    skip = recently_posted_keys(cooldown_days, platform="threads")
    eligible = [t for t in topics if f"trivia:{t}" not in skip]
    if not eligible:
        print("紹介できるトピックがありません（すべてクールダウン中）。")
        return

    topic = random.choice(eligible)
    print(f"今回のtrivia: {topic}")
    caption = generate_trivia_caption(topic)
    if not caption:
        print("告知文の生成に失敗しました。")
        return

    text = build_info_post_text(caption, tags="#楽天お買い物のコツ")
    try:
        post_id = _post_to_threads_notified(cfg, text)
        sns_record_posted(
            {"itemCode": f"trivia:{topic}", "itemUrl": "", "itemName": topic},
            platform="threads", post_id=post_id, category=f"trivia:{topic}",
        )
        print(f"✅ Threads投稿完了（trivia: {topic}） -> id={post_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 投稿失敗: {exc}")

    print(f"\n本日のThreads投稿累計 {sns_posted_today('threads')} 件")


def cmd_instagram(cfg: dict) -> None:
    """楽天の売れ筋商品をInstagramに画像付きで投稿する（リンクなし、プロフィールへ誘導）。

    Instagramのフィード投稿はキャプション内のリンクがクリックできないため、
    実際のクリック先はプロフィール欄のリンク（bio_link_page.pyが生成するページ）に
    集約する。投稿のたびにそのページも最新のA8リンク一覧に更新する。
    """
    import random

    from .bio_link_page import recent_instagram_items
    from .instagram_captions import build_instagram_post_text, generate_instagram_caption
    from .instagram_poster import post_to_instagram
    from .rakuten_api import RakutenAPI
    from .selector import gather_candidates
    from .sns_posted_log import posted_today as sns_posted_today
    from .sns_posted_log import record_posted as sns_record_posted
    from .sns_posted_log import recently_posted_keys

    ic = cfg.get("instagram", {}) or {}
    if not ic.get("enabled", True):
        print("Instagram投稿は設定(instagram.enabled)で無効になっています。")
        return
    if not _ensure_instagram_ready(cfg):
        return

    try:
        api = RakutenAPI(cfg["_app_id"], cfg["_access_key"], cfg["_affiliate_id"])
    except RuntimeError as exc:
        print(exc)
        return

    candidates = gather_candidates(cfg, api)
    cooldown_days = int(ic.get("repost_cooldown_days", 14))
    skip = recently_posted_keys(cooldown_days, platform="instagram")
    eligible = [it for it in candidates
                if it.get("imageUrl") and (it.get("itemCode") or it.get("itemUrl")) not in skip]
    if not eligible:
        print("紹介できる商品がありません（画像なし、またはすべてクールダウン中）。")
        return

    item = random.choice(eligible[: max(10, len(eligible) // 3)])  # 上位寄りからランダム
    print(f"今回のInstagram投稿: {item['itemName'][:40]}")

    caption = generate_instagram_caption(item)
    if not caption:
        print("キャプションの生成に失敗しました。")
        return

    disclosure = ic.get("disclosure") or "PR"
    text = build_instagram_post_text(caption, disclosure=disclosure)
    try:
        post_id = post_to_instagram(cfg["_instagram_token"], cfg["_instagram_user_id"],
                                     item["imageUrl"], text)
        sns_record_posted(item, platform="instagram", post_id=post_id,
                           category=item.get("genreId", ""))
        print(f"✅ Instagram投稿完了: {item['itemName'][:40]} -> id={post_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 投稿失敗: {exc}")

    # 買い時ナビの「Instagramで紹介中の商品」用に、最近の投稿商品を記録する
    try:
        recent_instagram_items(api)
    except Exception as exc:  # noqa: BLE001
        print(f"  Instagram紹介中の商品の記録に失敗（無視して続行）: {exc}")

    print(f"\n本日のInstagram投稿累計 {sns_posted_today('instagram')} 件")


def cmd_site(cfg: dict, skip_collect: bool = False) -> None:
    """買い時ナビ（kaidokinavi.com）の商品データを集めて、静的サイトを再生成する。"""
    from . import site_builder
    from .rakuten_api import RakutenAPI

    items = None
    if not skip_collect:
        api = RakutenAPI(cfg["_app_id"], cfg["_access_key"], cfg["_affiliate_id"])
        print("サイト用の商品データを集めています…")
        items = site_builder.collect(api)
    n = site_builder.build(items)
    print(f"サイトを生成しました: {n}ページ → {site_builder.OUT_DIR}")


def main() -> int:
    args = sys.argv[1:]
    cmd = args[0] if args else "run"
    dry_run = "--dry-run" in args

    if cmd == "login":
        cmd_login()
        return 0

    cfg = load_config()
    if cmd == "prepare":
        cmd_prepare(cfg)
    elif cmd == "post":
        cmd_post(cfg, dry_run=dry_run, serial="--serial" in args)
    elif cmd == "status":
        cmd_status(cfg)
    elif cmd in ("like", "follow", "unfollow"):
        from .engage import follow_round, like_round, unfollow_round

        slug = _room_slug(cfg)
        n = _arg_int(args, "--n", 20)
        if cmd == "like":
            like_round(cfg, n, feed=("home" if "--home" in args else "new"))
        elif cmd == "follow":
            follow_round(cfg, n, slug)
        else:
            unfollow_round(cfg, slug)
    elif cmd == "prune":
        from .pruner import prune

        max_delete = None
        for a in args:
            if a.startswith("--max="):
                max_delete = int(a.split("=", 1)[1])
            elif a == "--max" and args.index(a) + 1 < len(args):
                max_delete = int(args[args.index(a) + 1])
        prune(cfg, commit="--commit" in args, max_delete=max_delete)
    elif cmd == "run":
        cmd_run(cfg)
    elif cmd in ("sitedrop", "calendar", "trivia", "instagram"):
        from .job_lock import posting_lock

        with posting_lock() as acquired:
            if not acquired:
                print("  他の投稿ジョブが実行中のためスキップします"
                      "（手動実行とスケジューラが重なった可能性）。")
            elif cmd == "sitedrop":
                cmd_sitedrop(cfg)
            elif cmd == "calendar":
                cmd_calendar(cfg)
            elif cmd == "trivia":
                cmd_trivia(cfg)
            elif cmd == "instagram":
                cmd_instagram(cfg)
    elif cmd == "site":
        cmd_site(cfg, skip_collect="--no-collect" in args)
    elif cmd in ("-h", "--help", "help"):
        print(__doc__)
    else:
        print(f"不明なコマンド: {cmd}\n")
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
