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

from .captions import (
    captions_path,
    load_captions,
    save_drafts,
    write_prompt,
)
from .config import load_config
from .rakuten_api import RakutenAPI


def cmd_prepare(cfg: dict) -> None:
    from .selector import select_items

    try:
        api = RakutenAPI(cfg["_app_id"], cfg["_access_key"], cfg["_affiliate_id"])
    except RuntimeError as exc:
        print(exc)
        return
    items = select_items(cfg, api)
    if not items:
        print("条件を満たす候補が見つかりませんでした。config.yaml のしきい値を緩めてみてください。")
        return

    save_drafts(items)
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


def cmd_run(cfg: dict) -> None:
    cmd_prepare(cfg)
    if load_captions():
        cmd_post(cfg)
    else:
        print("\nキャプション待ちです。上の手順を済ませてから `post` を実行してください。")


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
    elif cmd in ("-h", "--help", "help"):
        print(__doc__)
    else:
        print(f"不明なコマンド: {cmd}\n")
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
