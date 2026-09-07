"""楽天のセール・イベント期間を判定して、投稿数の倍率を返す。

- 5と0のつく日: 日付から自動判定
- スーパーSALE / お買い物マラソン: 楽天イベントページから自動取得（ベストエフォート・日次キャッシュ）
- config の manual_events は常に優先
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from .config import DATA_DIR

CACHE_FILE = DATA_DIR / "sale_cache.json"
EVENT_URLS = [
    "https://event.rakuten.co.jp/campaign/",
    "https://event.rakuten.co.jp/supersale/",
    "https://event.rakuten.co.jp/marathon/",
]
# ページ本文から「MM/DD hh:mm ～ MM/DD hh:mm」的な期間を拾う
PERIOD_RE = re.compile(
    r"(\d{1,2})[/月](\d{1,2}).{0,8}?(\d{1,2})[:時]\d{2}\D{0,6}?"
    r"(\d{1,2})[/月](\d{1,2}).{0,8}?(\d{1,2})[:時]\d{2}"
)


def _parse_events_from_text(text: str, today: date) -> list[dict]:
    events = []
    for m in PERIOD_RE.finditer(text):
        sm, sd, _sh, em, ed, _eh = (int(x) for x in m.groups())
        year = today.year
        try:
            start = date(year, sm, sd)
            end = date(year if em >= sm else year + 1, em, ed)
        except ValueError:
            continue
        # 過去〜3ヶ月先の範囲だけ採用
        if start <= today + timedelta(days=90) and end >= today - timedelta(days=3):
            span = (end - start).days
            if 0 <= span <= 14:
                events.append({"name": "楽天イベント", "start": start.isoformat(),
                               "end": end.isoformat()})
    return events


def _scrape_events(today: date) -> list[dict]:
    try:
        import requests
    except ImportError:
        return []
    found: list[dict] = []
    for url in EVENT_URLS:
        try:
            r = requests.get(url, timeout=15,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.ok:
                found.extend(_parse_events_from_text(r.text, today))
        except Exception:  # noqa: BLE001
            continue
    # 重複除去
    uniq = {(e["start"], e["end"]): e for e in found}
    return list(uniq.values())


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _cached_events(today: date, auto_detect: bool) -> list[dict]:
    if not auto_detect:
        return []
    cache = _load_cache()
    if cache.get("date") == today.isoformat():
        return cache.get("events", [])
    events = _scrape_events(today)
    try:
        CACHE_FILE.write_text(
            json.dumps({"date": today.isoformat(), "events": events},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass
    return events


def _in_range(d: date, start: str, end: str) -> bool:
    try:
        return (datetime.fromisoformat(start).date()
                <= d <= datetime.fromisoformat(end).date())
    except (ValueError, TypeError):
        return False


def sale_status(cfg: dict, today: date | None = None) -> dict:
    """{'multiplier': float, 'reasons': [str]} を返す。"""
    today = today or date.today()
    sb = cfg.get("sale_boost", {})
    if not sb.get("enabled", True):
        return {"multiplier": 1.0, "reasons": []}

    multiplier = 1.0
    reasons: list[str] = []

    # 5と0のつく日
    if today.day % 5 == 0:
        m = float(sb.get("five_ten_day_multiplier", 1.3))
        multiplier = max(multiplier, m)
        reasons.append(f"5と0のつく日(×{m})")

    ev_mult = float(sb.get("event_multiplier", 1.8))

    # 手動イベント
    for e in sb.get("manual_events", []) or []:
        if _in_range(today, e.get("start"), e.get("end")):
            multiplier = max(multiplier, ev_mult)
            reasons.append(f"{e.get('name', 'イベント')}期間(×{ev_mult})")

    # 自動検知
    for e in _cached_events(today, sb.get("auto_detect", True)):
        if _in_range(today, e["start"], e["end"]):
            multiplier = max(multiplier, ev_mult)
            reasons.append(f"楽天イベント期間 {e['start']}〜{e['end']}(×{ev_mult})")
            break

    return {"multiplier": round(multiplier, 2), "reasons": reasons}
