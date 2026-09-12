"""楽天ROOM 半自動投稿ツール CLI。

使い方:
  python -m src.main login      初回だけ。ブラウザで楽天ROOMに手動ログイン
  python -m src.main prepare     商品を選定してキャプション用プロンプトを書き出す
  python -m src.main post        キャプションを読み込んで投稿画面に流し込む（最後は手動）
  python -m src.main run         prepare を実行し、キャプションがあれば post まで
  python -m src.main sns         値下がり・過去最安値の商品を検知してThreadsに自動投稿
  python -m src.main daily       投稿→いいね回り→フォロー回り→(削除)→(Threads投稿) を一括実行
"""
from __future__ import annotations

import sys

import json
import os
from datetime import date


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
    from .threads_poster import post_to_threads, refresh_long_lived_token

    sc = cfg.get("sns", {}) or {}
    if not sc.get("enabled", True):
        print("SNS投稿は設定(sns.enabled)で無効になっています。")
        return
    th = sc.get("threads", {}) or {}
    if not th.get("enabled", True):
        print("Threads投稿は設定(sns.threads.enabled)で無効になっています。")
        return
    if not cfg.get("_threads_token") or not cfg.get("_threads_user_id"):
        print(".env の THREADS_ACCESS_TOKEN / THREADS_USER_ID が未設定です。"
              "SETUP_THREADS.md の手順で取得してください。")
        return

    # 長期トークンは60日で失効。毎回延長しておくことで完全自動運用でも切れない。
    try:
        data = refresh_long_lived_token(cfg["_threads_token"])
        if data["access_token"] != cfg["_threads_token"]:
            from .config import update_env_value
            update_env_value("THREADS_ACCESS_TOKEN", data["access_token"])
            cfg["_threads_token"] = data["access_token"]
            print("  Threadsアクセストークンを延長しました。")
    except Exception as exc:  # noqa: BLE001
        print(f"  トークン延長に失敗（既存トークンで続行）: {exc}")

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
    disclosure = sc.get("disclosure") or th.get("disclosure") or "【PR】"
    lo, hi = th.get("interval_seconds", [20, 45])
    posted = 0
    for i, it in enumerate(picked):
        cap = caps.get(it["itemUrl"])
        if not cap:
            print(f"  告知文なし、スキップ: {it['itemName'][:40]}")
            continue
        text = build_post_text(it, cap, disclosure=disclosure)
        try:
            post_id = post_to_threads(
                cfg["_threads_token"], cfg["_threads_user_id"], text,
                image_url=it.get("imageUrl") or None,
            )
            sns_record_posted(it, platform="threads")
            posted += 1
            print(f"✅ Threads投稿完了: {it['itemName'][:40]} -> id={post_id}")
        except Exception as exc:  # noqa: BLE001
            print(f"❌ 投稿失敗: {it['itemName'][:40]}: {exc}")
        if i < len(picked) - 1:
            _time.sleep(random.uniform(float(lo), float(hi)))

    print(f"\nThreads投稿 {posted}/{len(picked)} 件完了（本日累計 {sns_posted_today('threads')} 件）")


def cmd_daily(cfg: dict) -> None:
    """投稿 → いいね回り → フォロー回り を順番に。ステップ間に自然な休憩。"""
    import random
    import time

    ec = cfg.get("engage", {}) or {}
    from .engage import follow_round, like_round

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
    elif cmd == "sns":
        cmd_sns(cfg)
    elif cmd in ("-h", "--help", "help"):
        print(__doc__)
    else:
        print(f"不明なコマンド: {cmd}\n")
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
