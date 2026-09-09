"""投稿済み商品の記録（重複投稿の防止 & 当日の投稿数カウント）。"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

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


def record_posted(item: dict, kind: str = "posted") -> None:
    """kind: "posted"（実際に投稿）/ "skipped_existing"（既存でスキップ）。"""
    log = load_posted()
    log.append({
        "itemCode": item.get("itemCode", ""),
        "itemUrl": item.get("itemUrl", ""),
        "itemName": item.get("itemName", ""),
        "kind": kind,
        "posted_at": datetime.now().isoformat(timespec="seconds"),
    })
    POSTED_FILE.write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def posted_today() -> int:
    """今日『実際に投稿した』件数（kind="posted" が明示されたもののみ数える）。"""
    today = date.today().isoformat()
    n = 0
    for rec in load_posted():
        if rec.get("kind") != "posted":
            continue
        if str(rec.get("posted_at", "")).startswith(today):
            n += 1
    return n
