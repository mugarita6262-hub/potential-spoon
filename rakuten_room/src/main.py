"""楽天ROOM 半自動投稿ツール CLI。

使い方:
  python -m src.main login      初回だけ。ブラウザで楽天ROOMに手動ログイン
  python -m src.main prepare     商品を選定してキャプション用プロンプトを書き出す
  python -m src.main post        キャプションを読み込んで投稿画面に流し込む（最後は手動）
  python -m src.main run         prepare を実行し、キャプションがあれば post まで
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


def cmd_post(cfg: dict, dry_run: bool = False, serial: bool = False) -> None:
    from .poster import post_drafts, post_drafts_tabs

    if serial or dry_run:
        post_drafts(cfg, dry_run=dry_run)
    else:
        post_drafts_tabs(cfg)


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


def cmd_run(cfg: dict) -> None:
    if load_captions():
        print("今日の準備は済んでいます（紹介文あり）。投稿タブを開きます。\n")
    else:
        cmd_prepare(cfg)
    if load_captions():
        cmd_post(cfg)
    else:
        print("\nキャプション待ちです。上の手順を済ませてから もう一度どうぞ。")


def cmd_daily(cfg: dict) -> None:
    """投稿 → いいね回り → フォロー回り を順番に。"""
    ec = cfg.get("engage", {}) or {}
    from .engage import follow_round, like_round

    print("========== 1/3 投稿 ==========")
    cmd_run(cfg)

    print("\n========== 2/3 いいね回り ==========")
    try:
        like_round(cfg, int(ec.get("daily_likes", 30)))
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"いいね回りでエラー: {exc}")

    print("\n========== 3/3 フォロー回り ==========")
    try:
        follow_round(cfg, int(ec.get("daily_follows", 15)), _room_slug(cfg))
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"フォロー回りでエラー: {exc}")

    print("\n========== おまかせ完了。おつかれさまでした ==========")


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
    elif cmd in ("-h", "--help", "help"):
        print(__doc__)
    else:
        print(f"不明なコマンド: {cmd}\n")
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
