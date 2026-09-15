"""楽天ROOM 半自動投稿ツール CLI。

使い方:
  python -m src.main login      初回だけ。ブラウザで楽天ROOMに手動ログイン
  python -m src.main prepare     商品を選定してキャプション用プロンプトを書き出す
  python -m src.main post        キャプションを読み込んで投稿画面に流し込む（最後は手動）
  python -m src.main run         prepare を実行し、キャプションがあれば post まで
  python -m src.main collect     調査専用: 広いジャンルの価格スナップショットだけ集める（無料）
  python -m src.main sns         値下がり・過去最安値の商品を検知してThreadsに自動投稿
  python -m src.main a8          A8アフィリリンクをローテーションでThreadsに自動投稿
  python -m src.main digest      ジャンル別売れ筋ダイジェストをThreadsに投稿（リンクあり）
  python -m src.main trend       ジャンルの価格トレンド速報をThreadsに投稿（リンクなし）
  python -m src.main calendar    セール・お得日のリマインドをThreadsに投稿（リンクなし）
  python -m src.main trivia      ミニ知識・あるあるネタをThreadsに投稿（リンクなし）
  python -m src.main instagram   楽天の売れ筋商品を画像付きでInstagramに投稿（プロフィールへ誘導）
  python -m src.main reply "相手の投稿本文"   リプライ下書きを3案作る（投稿は手動）
  python -m src.main insights    Threads投稿の反応をジャンル・商品別に集計して表示
  python -m src.main daily       投稿→いいね回り→フォロー回り→(削除)→(SNS投稿) を一括実行
"""
from __future__ import annotations

import sys

import json
import os
from datetime import date

# コンソールの既定コードページ（Windowsのcp932等）だと絵文字（✅❌🎯など）の
# print()がUnicodeEncodeErrorで落ちるため、標準出力/エラーをUTF-8化しておく。
# GUI（gui.py）はサブプロセスにPYTHONIOENCODING=utf-8を渡すため元々問題ないが、
# ターミナルから直接CLIを叩いた場合の保険として。
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
    write_prompt,
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

    p = write_prompt(items)
    print(f"\nプロンプトを書き出しました: {p}")
    print("この中身をまるごと Claude に貼り、返ってきた JSON を次に保存してください:")
    print(f"  {captions_path()}")
    print("そのあと `python -m src.main post` を実行します。")


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
    from .timing import posting_advice

    plan = load_plan()
    adv = posting_advice(cfg, {"reasons": plan.get("reasons", [])})
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
    print(f"1回のタブ数    : {cfg.get('post_batch_size', target)} 件")
    print(f"投稿タイミング : {adv['hint']}")


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
    preview = text.split("\n", 1)[0][:40]
    notify(
        f"投稿しました: {preview}\n"
        "最初の30〜60分の反応が伸びを左右します。よければ今のうちに"
        "いいね・返信しておくと効果的です。",
        title="rakuten_room: posted, engage now",
    )
    return post_id


def cmd_collect(cfg: dict) -> None:
    """調査専用: Claude APIもThreads投稿も使わず、広いジャンルの価格スナップショットだけ集める。

    値下がり検知の精度を上げるための下ごしらえ。何度・何ジャンル実行してもコストは
    楽天APIの呼び出し回数だけ（実質無料）。
    """
    import copy

    from .rakuten_api import RakutenAPI
    from .selector import gather_candidates
    from . import price_history

    rc = cfg.get("research", {}) or {}
    if not rc.get("enabled", True):
        print("調査収集は設定(research.enabled)で無効になっています。")
        return

    try:
        api = RakutenAPI(cfg["_app_id"], cfg["_access_key"], cfg["_affiliate_id"])
    except RuntimeError as exc:
        print(exc)
        return

    # sources.ranking.genre_ids に research.extra_genre_ids を足した広いジャンルで集める
    # （投稿対象の選定ロジックには影響させないよう、cfgのコピー上で拡張する）
    wide_cfg = copy.deepcopy(cfg)
    base_ids = list(wide_cfg["sources"]["ranking"]["genre_ids"])
    extra_ids = list(rc.get("extra_genre_ids", []) or [])
    wide_cfg["sources"]["ranking"]["genre_ids"] = sorted(set(base_ids + extra_ids))

    print(f"調査ジャンル数: {len(wide_cfg['sources']['ranking']['genre_ids'])}"
          f"（内訳: 通常{len(base_ids)} + 調査専用{len(extra_ids)}）")
    candidates = gather_candidates(wide_cfg, api)
    price_history.record_snapshot(candidates)
    print(f"価格スナップショットを記録しました: {len(candidates)} 件")


def cmd_sns(cfg: dict) -> None:
    """値下がり・過去最安値の商品を検知して Threads に自動投稿する（完全自動）。"""
    import random
    import time as _time

    from .rakuten_api import RakutenAPI
    from .selector import gather_candidates
    from .sns_captions import build_post_text, generate_sns_captions
    from .sns_posted_log import posted_today as sns_posted_today
    from .sns_posted_log import record_posted as sns_record_posted
    from .sns_selector import select_sale_items

    sc = cfg.get("sns", {}) or {}
    if not sc.get("enabled", True):
        print("SNS投稿は設定(sns.enabled)で無効になっています。")
        return
    th = sc.get("threads", {}) or {}
    if not th.get("enabled", True):
        print("Threads投稿は設定(sns.threads.enabled)で無効になっています。")
        return
    if not _ensure_threads_ready(cfg):
        return

    try:
        api = RakutenAPI(cfg["_app_id"], cfg["_access_key"], cfg["_affiliate_id"])
    except RuntimeError as exc:
        print(exc)
        return

    print("値下がり・過去最安値の商品を探しています…")
    candidates = gather_candidates(cfg, api)
    picked = select_sale_items(
        candidates,
        top_n=int(th.get("post_count", 3)),
        min_discount_pct=float(sc.get("min_discount_pct", 10)),
        lookback_days=int(sc.get("lookback_days", 30)),
        cooldown_days=int(sc.get("repost_cooldown_days", 30)),
        platform="threads",
    )
    if not picked:
        print("今日は値下がり・過去最安値の商品が見つかりませんでした（対象なし）。")
        return

    print(f"対象 {len(picked)} 件:")
    for it in picked:
        tag = "過去最安" if it["is_all_time_low"] else f"{it['drop_pct']:.0f}%OFF"
        print(f"  - [{tag}] {it['itemName'][:40]}  {it['price']:,}円")

    caps = generate_sns_captions(picked)
    disclosure = sc.get("disclosure") or th.get("disclosure") or "PR"
    lo, hi = th.get("interval_seconds", [20, 45])
    posted = 0
    for i, it in enumerate(picked):
        cap = caps.get(it["itemUrl"])
        if not cap:
            print(f"  告知文なし、スキップ: {it['itemName'][:40]}")
            continue
        text = build_post_text(it, cap, disclosure=disclosure)
        try:
            post_id = _post_to_threads_notified(cfg, text, image_url=it.get("imageUrl") or None)
            sns_record_posted(it, platform="threads", post_id=post_id,
                               category=it.get("genreId", ""))
            posted += 1
            print(f"✅ Threads投稿完了: {it['itemName'][:40]} -> id={post_id}")
        except Exception as exc:  # noqa: BLE001
            print(f"❌ 投稿失敗: {it['itemName'][:40]}: {exc}")
        if i < len(picked) - 1:
            _time.sleep(random.uniform(float(lo), float(hi)))

    print(f"\nThreads投稿 {posted}/{len(picked)} 件完了（本日累計 {sns_posted_today('threads')} 件）")


def cmd_a8(cfg: dict) -> None:
    """A8アフィリリンクをローテーションでThreadsに自動投稿する（値下がり検知とは無関係）。"""
    from .a8_captions import build_post_text, generate_a8_captions
    from .a8_selector import pick_next
    from .sns_posted_log import posted_today as sns_posted_today
    from .sns_posted_log import record_posted as sns_record_posted

    ac = cfg.get("a8", {}) or {}
    if not ac.get("enabled", True):
        print("A8投稿は設定(a8.enabled)で無効になっています。")
        return
    if not _ensure_threads_ready(cfg):
        return

    link = pick_next(cooldown_days=int(ac.get("repost_cooldown_days", 10)))
    if not link:
        print("投稿できるA8リンクがありません"
              "（data/a8_links.yaml が空、またはすべてクールダウン中）。")
        return

    print(f"今回のA8紹介: {link['program_name'][:40]}")
    caps = generate_a8_captions([link])
    cap = caps.get(link["program_id"])
    if not cap:
        print("紹介文の生成に失敗しました。今回はスキップします。")
        return

    disclosure = ac.get("disclosure") or "PR"
    text = build_post_text(link, cap, disclosure=disclosure)
    try:
        post_id = _post_to_threads_notified(cfg, text)
        sns_record_posted(
            {"itemCode": link["program_id"], "itemUrl": link["url"],
             "itemName": link["program_name"]},
            platform="threads", post_id=post_id,
            category=link.get("genre") or link["program_name"][:30],
        )
        print(f"✅ Threads投稿完了: {link['program_name'][:40]} -> id={post_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 投稿失敗: {link['program_name'][:40]}: {exc}")

    print(f"\n本日のThreads投稿累計 {sns_posted_today('threads')} 件")


def _all_genre_ids(cfg: dict) -> list[int]:
    """sources.ranking.genre_ids ＋ research.extra_genre_ids（重複除去）。"""
    base = list(cfg["sources"]["ranking"]["genre_ids"])
    extra = list((cfg.get("research", {}) or {}).get("extra_genre_ids", []) or [])
    return sorted(set(base + extra))


def cmd_digest(cfg: dict) -> None:
    """条件に依存しないネタ①: ジャンル別売れ筋ダイジェスト（リンクあり・PRあり）。

    値下がりが無くても、ランキング自体をネタにできるので出現頻度が高い。
    """
    import random

    from .content_captions import build_digest_post_text, generate_digest_caption
    from .insights import GENRE_NAMES
    from .rakuten_api import RakutenAPI
    from .sns_posted_log import posted_today as sns_posted_today
    from .sns_posted_log import record_posted as sns_record_posted
    from .sns_posted_log import recently_posted_keys

    dc = cfg.get("digest", {}) or {}
    if not dc.get("enabled", True):
        print("digest投稿は設定(digest.enabled)で無効になっています。")
        return
    if not _ensure_threads_ready(cfg):
        return

    try:
        api = RakutenAPI(cfg["_app_id"], cfg["_access_key"], cfg["_affiliate_id"])
    except RuntimeError as exc:
        print(exc)
        return

    cooldown_days = int(dc.get("repost_cooldown_days", 5))
    skip = recently_posted_keys(cooldown_days, platform="threads")
    candidates_genres = [g for g in _all_genre_ids(cfg) if f"digest:{g}" not in skip]
    if not candidates_genres:
        print("紹介できるジャンルがありません（すべてクールダウン中）。")
        return

    genre_id = random.choice(candidates_genres)
    genre_name = GENRE_NAMES.get(str(genre_id), f"ジャンル{genre_id}")

    try:
        items = api.ranking(int(genre_id), 5)
    except Exception as exc:  # noqa: BLE001
        print(f"ランキング取得に失敗: {exc}")
        return
    if len(items) < 3:
        print("ランキング件数が足りません。")
        return

    print(f"今回のdigest: {genre_name}")
    caption = generate_digest_caption(genre_name, items)
    if not caption:
        print("紹介文の生成に失敗しました。")
        return

    disclosure = dc.get("disclosure") or "PR"
    text = build_digest_post_text(items[0], caption, disclosure=disclosure)
    try:
        post_id = _post_to_threads_notified(cfg, text)
        sns_record_posted(
            {"itemCode": f"digest:{genre_id}", "itemUrl": items[0].get("itemUrl", ""),
             "itemName": f"{genre_name}ダイジェスト"},
            platform="threads", post_id=post_id, category=f"digest:{genre_name}",
        )
        print(f"✅ Threads投稿完了（digest: {genre_name}） -> id={post_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 投稿失敗: {exc}")

    print(f"\n本日のThreads投稿累計 {sns_posted_today('threads')} 件")


def cmd_trend(cfg: dict) -> None:
    """条件に依存しないネタ②: ジャンルの価格トレンド速報（リンクなし・PR不要）。

    個別商品の値下がりより出現条件が緩く（ジャンル全体の平均変化で判定）、
    投稿頻度を上げやすい。リンクを含まないためPR表記も不要。
    """
    import copy

    from .content_captions import build_info_post_text, generate_trend_caption
    from .insights import GENRE_NAMES
    from .rakuten_api import RakutenAPI
    from .selector import gather_candidates
    from .sns_posted_log import posted_today as sns_posted_today
    from .sns_posted_log import record_posted as sns_record_posted
    from .sns_posted_log import recently_posted_keys
    from .trend import genre_trend

    tc = cfg.get("trend", {}) or {}
    if not tc.get("enabled", True):
        print("trend投稿は設定(trend.enabled)で無効になっています。")
        return
    if not _ensure_threads_ready(cfg):
        return

    try:
        api = RakutenAPI(cfg["_app_id"], cfg["_access_key"], cfg["_affiliate_id"])
    except RuntimeError as exc:
        print(exc)
        return

    wide_cfg = copy.deepcopy(cfg)
    wide_cfg["sources"]["ranking"]["genre_ids"] = _all_genre_ids(cfg)
    candidates = gather_candidates(wide_cfg, api)

    trends = genre_trend(candidates, lookback_days=int(tc.get("lookback_days", 7)),
                          min_sample=int(tc.get("min_sample", 3)))
    if not trends:
        print("トレンドを計算できるジャンルがありません（データ不足。collectを数日回してください）。")
        return

    cooldown_days = int(tc.get("repost_cooldown_days", 5))
    skip = recently_posted_keys(cooldown_days, platform="threads")
    min_pct = float(tc.get("min_pct_change", 3.0))
    eligible = [t for t in trends if f"trend:{t['genre_id']}" not in skip
                and abs(t["pct_change"]) >= min_pct]
    if not eligible:
        print("紹介できるトレンドがありません（変化が小さいか、すべてクールダウン中）。")
        return

    top = eligible[0]
    genre_name = GENRE_NAMES.get(top["genre_id"], f"ジャンル{top['genre_id']}")
    print(f"今回のtrend: {genre_name} ({top['pct_change']:+.1f}%)")

    caption = generate_trend_caption(genre_name, top["pct_change"], top["direction"])
    if not caption:
        print("告知文の生成に失敗しました。")
        return

    text = build_info_post_text(caption)
    try:
        post_id = _post_to_threads_notified(cfg, text)
        sns_record_posted(
            {"itemCode": f"trend:{top['genre_id']}", "itemUrl": "",
             "itemName": f"{genre_name}トレンド"},
            platform="threads", post_id=post_id, category=f"trend:{genre_name}",
        )
        print(f"✅ Threads投稿完了（trend: {genre_name}） -> id={post_id}")
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

    text = build_info_post_text(caption, tags="#暮らしの豆知識")
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

    from .a8_selector import load_links
    from .bio_link_page import update_bio_page
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

    # プロフィールのリンクインバイオページを最新のA8リンクで更新
    try:
        if update_bio_page(load_links()):
            print("  リンクインバイオページを更新しました。")
    except Exception as exc:  # noqa: BLE001
        print(f"  リンクインバイオページの更新に失敗（無視して続行）: {exc}")

    print(f"\n本日のInstagram投稿累計 {sns_posted_today('instagram')} 件")


def cmd_reply(target_text: str) -> None:
    """他アカウントの投稿へのリプライ下書きをClaudeに考えてもらう（投稿は手動）。

    Threads公式APIは他人の投稿を検索・発見する機能を提供していないため、
    「良さそうな投稿を見つける」のは引き続き人の仕事。ここでは見つけてきた
    投稿の文面を渡すと、返信文の候補を考える部分だけ肩代わりする。
    いいね数よりリプライ数の方がThreadsの伸びを左右するとされているため、
    質の良いリプライを増やすための道具。
    """
    from .content_captions import generate_reply_drafts

    if not target_text.strip():
        print('使い方: python -m src.main reply "相手の投稿本文"')
        return

    drafts = generate_reply_drafts(target_text, n=3)
    if not drafts:
        print("下書きの生成に失敗しました。")
        return

    print("\n--- リプライ下書き（この中から選ぶ・手直ししてThreadsアプリで投稿） ---")
    for i, d in enumerate(drafts, 1):
        print(f"{i}. {d}")


def cmd_insights(cfg: dict) -> None:
    """Threads投稿の反応（いいね・閲覧数）をジャンル・商品別に集計して表示する。"""
    from .insights import report_by_category, sync_insights

    if not cfg.get("_threads_token"):
        print(".env の THREADS_ACCESS_TOKEN が未設定です。")
        return

    print("投稿から24時間以上経ったものの反応を取得しています…")
    try:
        n = sync_insights(cfg["_threads_token"])
        print(f"  {n}件のインサイトを更新しました。\n")
    except Exception as exc:  # noqa: BLE001
        print(f"  インサイト取得でエラー: {exc}\n")

    rows = report_by_category()
    if not rows:
        print("まだ反応データがありません（投稿から24時間以上、かつ`threads_manage_insights`"
              "権限付きトークンが必要です）。")
        return

    print("反応が良い順（平均いいね数）:")
    print(f"{'カテゴリ':<28} {'平均いいね':>8} {'平均閲覧':>8} {'平均リポスト':>10} {'件数':>4}")
    for r in rows:
        print(f"{r['category'][:28]:<28} {r['avg_likes']:>8} {r['avg_views']:>8} "
              f"{r['avg_reposts']:>10} {r['count']:>4}")

    # ここから先は「調査結果を自分で解釈しなくていい」ようにする自動判定。
    # 楽天ジャンルは反応が良ければconfig.yamlを書き換えて投稿候補に自動昇格、
    # A8は自動申請できないのでdocs/A8アフィリリンク取得依頼.mdに依頼を自動追記する。
    from .optimizer import auto_promote_rakuten_genres, suggest_a8_expansion

    actions = auto_promote_rakuten_genres(rows) + suggest_a8_expansion(rows)
    if actions:
        print("\n次のアクション:")
        for msg in actions:
            print(f"  {msg}")


def cmd_daily(cfg: dict) -> None:
    """サーバーとの差分同期 → 投稿 → いいね回り → フォロー回り を順番に。ステップ間に自然な休憩。"""
    import random
    import time

    ec = cfg.get("engage", {}) or {}
    from .engage import follow_round, like_round
    from .server_sync import sync_with_server

    try:
        sync_with_server()
    except Exception as exc:  # noqa: BLE001
        print(f"サーバー同期でエラー（無視して続行）: {exc}")

    def _rest():
        lo, hi = ec.get("daily_gap_minutes", [2, 6])
        s = random.uniform(float(lo) * 60, float(hi) * 60)
        print(f"\n（{int(s / 60)}分ほど休憩してから次へ…）")
        time.sleep(s)

    print("━━━━━ ステップ1 / 3：投稿（今日ぶん）━━━━━")
    cmd_run(cfg, full_day=True)

    _rest()
    print(f"━━━━━ ステップ2 / 3：いいね回り（最大 {int(ec.get('daily_likes', 30))} 件）━━━━━")
    try:
        like_round(cfg, int(ec.get("daily_likes", 30)))
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"いいね回りでエラー: {exc}")

    _rest()
    print(f"━━━━━ ステップ3 / 3：フォロー回り（最大 {int(ec.get('daily_follows', 15))} 件）━━━━━")
    try:
        follow_round(cfg, int(ec.get("daily_follows", 15)), _room_slug(cfg))
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"フォロー回りでエラー: {exc}")

    n_prune = int(ec.get("daily_prune", 0))
    if n_prune > 0:
        _rest()
        print(f"━━━━━ おまけ：古い投稿を {n_prune} 件削除（登録上限の余裕づくり）━━━━━")
        try:
            from .pruner import prune
            prune(cfg, commit=True, max_delete=n_prune)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"削除でエラー: {exc}")

    sc = cfg.get("sns", {}) or {}
    if sc.get("enabled", True) and sc.get("run_in_daily", True):
        _rest()
        print("━━━━━ おまけ：値下がり品をThreadsへ自動投稿 ━━━━━")
        try:
            cmd_sns(cfg)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"SNS投稿でエラー: {exc}")

    ac = cfg.get("a8", {}) or {}
    if ac.get("enabled", True) and ac.get("run_in_daily", True):
        _rest()
        print("━━━━━ おまけ：A8リンクをThreadsへローテーション投稿 ━━━━━")
        try:
            cmd_a8(cfg)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"A8投稿でエラー: {exc}")

    print("\n━━━━━ おまかせ完了。おつかれさまでした ━━━━━")


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
    elif cmd == "daily":
        cmd_daily(cfg)
    elif cmd == "collect":
        cmd_collect(cfg)
    elif cmd == "sns":
        cmd_sns(cfg)
    elif cmd == "a8":
        cmd_a8(cfg)
    elif cmd == "digest":
        cmd_digest(cfg)
    elif cmd == "trend":
        cmd_trend(cfg)
    elif cmd == "calendar":
        cmd_calendar(cfg)
    elif cmd == "trivia":
        cmd_trivia(cfg)
    elif cmd == "instagram":
        cmd_instagram(cfg)
    elif cmd == "reply":
        cmd_reply(" ".join(args[1:]))
    elif cmd == "insights":
        cmd_insights(cfg)
    elif cmd in ("-h", "--help", "help"):
        print(__doc__)
    else:
        print(f"不明なコマンド: {cmd}\n")
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
