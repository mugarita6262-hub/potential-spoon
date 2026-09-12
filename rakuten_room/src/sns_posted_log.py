"""SNS（Threads/X等）投稿済みの記録。重複投稿の防止と、当日の投稿数カウント用。

`posted.json`（ROOM投稿の記録）とは別ファイル。プラットフォーム別に扱う。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from .config import DATA_DIR

SNS_POSTED_FILE = DATA_DIR / "sns_posted.json"


def load_posted() -> list[dict]:
    if SNS_POSTED_FILE.exists():
        return json.loads(SNS_POSTED_FILE.read_text(encoding="utf-8"))
    return []


def recently_posted_keys(within_days: int, platform: str | None = None) -> set[str]:
    cutoff = datetime.now() - timedelta(days=within_days)
    keys: set[str] = set()
    for rec in load_posted():
        if platform and rec.get("platform") != platform:
            continue
        try:
            when = datetime.fromisoformat(rec["posted_at"])
        except (KeyError, ValueError):
            continue
        if when >= cutoff:
            keys.add(rec.get("itemCode") or rec.get("itemUrl", ""))
    return keys


def record_posted(item: dict, platform: str, post_id: str = "",
                   category: str = "") -> None:
    """post_id・category を渡しておくと、後で insights コマンドが反応を集計できる。"""
    log = load_posted()
    log.append({
        "itemCode": item.get("itemCode", ""),
        "itemUrl": item.get("itemUrl", ""),
        "itemName": item.get("itemName", ""),
        "platform": platform,
        "drop_pct": item.get("drop_pct", 0),
        "is_all_time_low": item.get("is_all_time_low", False),
        "post_id": post_id,
        "category": category,
        "posted_at": datetime.now().isoformat(timespec="seconds"),
    })
    SNS_POSTED_FILE.write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def posted_today(platform: str) -> int:
    today = date.today().isoformat()
    return sum(
        1 for rec in load_posted()
        if rec.get("platform") == platform
        and str(rec.get("posted_at", "")).startswith(today)
    )
