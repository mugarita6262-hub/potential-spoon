"""KDP企画ツール CLI。

使い方:
  python -m src.main ideas [テーマのヒント]   企画候補を生成して表示・保存
"""
from __future__ import annotations

import json
import sys

from .config import DATA_DIR, load_env


def cmd_ideas(theme: str) -> None:
    from .ideas import generate_ideas, print_ideas

    print("企画を生成中..." + (f"（テーマ: {theme}）" if theme else ""))
    ideas = generate_ideas(theme)
    print_ideas(ideas)

    path = DATA_DIR / "ideas_latest.json"
    path.write_text(json.dumps(ideas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存しました: {path}")


def main() -> int:
    load_env()
    args = sys.argv[1:]
    cmd = args[0] if args else "ideas"
    if cmd == "ideas":
        cmd_ideas(" ".join(args[1:]))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
