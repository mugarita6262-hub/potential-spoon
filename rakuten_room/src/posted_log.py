"""投稿済み商品の記録（重複投稿の防止）。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .config import POSTED_FILE


def load_posted() -> list[dict]:
    if POSTED_FILE.exists():
        return json.loads(POSTED_FILE.read_text(encoding="utf-8"))
    return []


def recently_posted_keys(within_days: int) -> set[str]:
    cutoff = datetime.now() - timedelta(days=within_days)
    keys: set[str] = set()
    for rec in load_posted():
        try:
            when = datetime.fromisoformat(rec["posted_at"])
        except (KeyError, ValueError):
            continue
        if when >= cutoff:
            keys.add(rec.get("itemCode") or rec.get("itemUrl", ""))
    return keys


def record_posted(item: dict) -> None:
    log = load_posted()
    log.append({
        "itemCode": item.get("itemCode", ""),
        "itemUrl": item.get("itemUrl", ""),
        "itemName": item.get("itemName", ""),
        "posted_at": datetime.now().isoformat(timespec="seconds"),
    })
    POSTED_FILE.write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8"
    )
