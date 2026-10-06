"""直近のThreads投稿の書き出しを覚えておき、次の投稿文生成で被らないようにする。

投稿文は毎回独立に生成していて、AIは自分の直前の投稿を知らない。そのうえ全プロンプトに
「季節は秋」と入れているので、2026-10-06に「秋になると…」で始まる投稿が3つ続いた。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .config import DATA_DIR

_FILE = DATA_DIR / "recent_openings.json"
_KEEP = 40


def _load() -> list[dict]:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def record(text: str) -> None:
    first = text.strip().split("\n", 1)[0].strip()[:60]
    if not first:
        return
    rows = _load() + [{"at": datetime.now().isoformat(timespec="seconds"), "text": first}]
    try:
        _FILE.write_text(json.dumps(rows[-_KEEP:], ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def recent(days: int = 2, limit: int = 10) -> list[str]:
    since = (datetime.now() - timedelta(days=days)).isoformat()
    return [r["text"] for r in _load() if r.get("at", "") >= since][-limit:]
