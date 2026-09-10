"""投稿の好機を判定する。

- 5と0のつく日 / 毎月4・9日（セール前日パターン、ROOM編集部の更新タイミング）
- スーパーSALE・マラソン期間中
- 閲覧が多い時間帯（朝・昼・夜）
"""
from __future__ import annotations

from datetime import date, datetime

PEAK_HOURS = {
    (7, 9): "朝の通勤時間",
    (12, 13): "昼休み",
    (20, 24): "夜のゴールデンタイム",
}


def _peak(now: datetime) -> str | None:
    for (lo, hi), name in PEAK_HOURS.items():
        if lo <= now.hour < hi:
            return name
    return None


def posting_advice(cfg: dict, sale: dict | None = None,
                   now: datetime | None = None) -> dict:
    """{'good': bool, 'reasons': [str], 'hint': str} を返す。"""
    now = now or datetime.now()
    d: date = now.date()
    reasons: list[str] = []
    day_good = False

    if d.day in (4, 9):
        reasons.append(f"{d.day}日はセール前日・ROOM更新の狙い目")
        day_good = True
    if d.day % 5 == 0:
        reasons.append("5と0のつく日")
        day_good = True
    for r in (sale or {}).get("reasons", []):
        if "SALE" in r or "マラソン" in r or "イベント" in r:
            reasons.append("セール開催中")
            day_good = True
            break

    peak = _peak(now)
    good = day_good and peak is not None

    if good:
        hint = f"いま投稿の好機（{peak}）。まとめて投稿してOK。"
    elif day_good and not peak:
        nxt = _next_peak_label(now)
        hint = f"今日は投稿日和。閲覧が増える{nxt}に投稿すると効果的。"
    elif peak and not day_good:
        hint = f"{peak}で閲覧は多め。投稿しても可。"
    else:
        hint = "急ぎでなければ、夜21時台や5・0のつく日にまとめると効果的。"

    return {"good": good, "day_good": day_good, "peak": peak,
            "reasons": reasons, "hint": hint}


def _next_peak_label(now: datetime) -> str:
    h = now.hour
    if h < 7:
        return "朝7時台"
    if h < 12:
        return "昼12時台"
    if h < 20:
        return "夜21時台"
    return "明日の朝"
