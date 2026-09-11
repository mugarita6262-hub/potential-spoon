"""環境変数の読み込み。自分の .env → 無ければ隣の rakuten_room/.env の
ANTHROPIC_API_KEY を借りる（秘密情報を複製しないため）。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _read_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value:
            os.environ.setdefault(key, value)


def load_env() -> None:
    _read_env_file(ROOT / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        _read_env_file(ROOT.parent / "rakuten_room" / ".env")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
