"""data/a8_links.yaml（A8・バリューコマースの提携リンク）を読む。買い時ナビのサービス枠が使う。"""
from __future__ import annotations

from pathlib import Path

import yaml

from .config import DATA_DIR

LINKS_FILE = DATA_DIR / "a8_links.yaml"


def load_links(path: Path | None = None) -> list[dict]:
    p = path or LINKS_FILE
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return [row for row in data if row.get("url")]

