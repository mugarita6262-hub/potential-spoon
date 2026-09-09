"""楽天のセール・イベント日を判定して、その日の投稿数の倍率を返す。

- 5と0のつく日: 日付から判定
- スーパーSALE / お買い物マラソン 等: 候補商品名にセール表記が多ければ開催中とみなす
  （event.rakuten.co.jp のスクレイプより、実データ由来なので堅い）
- config の manual_events は常に優先
"""
from __future__ import annotations

import re
from datetime import date, datetime

EVENT_KEYWORDS = re.compile(
    r"スーパー\s*SALE|スーパーセール|お買い物マラソン|買い回り|買いまわり|"
    r"勝ったら倍|ワンダフルデー|楽天スーパー|39ショップ"
)
# スーパーSALE / マラソンの「エントリー期間」表記。開催中は多数の商品につく
SALE_WINDOW = re.compile(r"\d{1,2}/\d{1,2}\s*20:00\s*[〜～\-–]\s*\d{1,2}/\d{1,2}\s*0?1:59")


def _in_range(d: date, start: str, end: str) -> bool:
    try:
        return (datetime.fromisoformat(str(start)).date()
                <= d <= datetime.fromisoformat(str(end)).date())
    except (ValueError, TypeError):
        return False


def _event_signal(items: list[dict]) -> tuple[float, int]:
    """(セール表記の割合, 同一エントリー期間表記の商品数) を返す。"""
    if not items:
        return 0.0, 0
    names = [it.get("itemName", "") for it in items]
    kw_hit = sum(1 for n in names if EVENT_KEYWORDS.search(n))
    windows: dict[str, int] = {}
    for n in names:
        m = SALE_WINDOW.search(n)
        if m:
            windows[m.group(0).replace(" ", "")] = windows.get(
                m.group(0).replace(" ", ""), 0) + 1
    max_window = max(windows.values()) if windows else 0
    return kw_hit / len(items), max_window


def sale_status(cfg: dict, items: list[dict] | None = None,
                today: date | None = None) -> dict:
    """{'multiplier': float, 'reasons': [str]} を返す。"""
    today = today or date.today()
    sb = cfg.get("sale_boost", {}) or {}
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

    # 商品名からの自動検知
    if sb.get("auto_detect", True) and items is not None:
        thr = float(sb.get("event_name_ratio", 0.12))
        ratio, window_hits = _event_signal(items)
        if ratio >= thr:
            multiplier = max(multiplier, ev_mult)
            reasons.append(f"セール開催中らしい(候補の{ratio:.0%}にセール表記, ×{ev_mult})")
        elif window_hits >= 3:
            multiplier = max(multiplier, ev_mult)
            reasons.append(f"セール開催中(同一エントリー期間の商品{window_hits}件, ×{ev_mult})")

    cap = float(sb.get("max_multiplier", 2.0))
    return {"multiplier": round(min(multiplier, cap), 2), "reasons": reasons}
