"""A8アフィリリンクのローテーション選定。

data/a8_links.yaml に登録されたリンクの中から、最後にSNS投稿してから
一番日数が経っている（＝一度も投稿していないものを最優先）1件を選ぶ。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from .config import DATA_DIR
from .sns_posted_log import load_posted

LINKS_FILE = DATA_DIR / "a8_links.yaml"


def load_links(path: Path | None = None) -> list[dict]:
    p = path or LINKS_FILE
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return [row for row in data if row.get("url")]


def _last_posted_at(program_id: str, platform: str) -> datetime | None:
    latest = None
    for rec in load_posted():
        if rec.get("platform") != platform or rec.get("itemCode") != program_id:
            continue
        try:
            when = datetime.fromisoformat(rec["posted_at"])
        except (KeyError, ValueError):
            continue
        if latest is None or when > latest:
            latest = when
    return latest


def pick_next(cooldown_days: int = 10, platform: str = "threads") -> dict | None:
    """クールダウンを満たす中から、一番長く投稿していない（未投稿優先）1件を返す。"""
    links = load_links()
    if not links:
        return None

    now = datetime.now()
    candidates: list[tuple[float, dict]] = []
    for link in links:
        last = _last_posted_at(link["program_id"], platform)
        if last is None:
            candidates.append((float("inf"), link))
            continue
        days_since = (now - last).total_seconds() / 86400
        if days_since >= cooldown_days:
            candidates.append((days_since, link))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]
