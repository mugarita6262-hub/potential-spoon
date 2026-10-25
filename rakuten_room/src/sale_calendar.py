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
# 商品名の「10/24 20:00〜10/27 9:59」のような期間の表記。今がその期間内の商品が3件以上あれば、セール開催中とみなす
# （2026-10-25: 以前は終わりが「1:59」の形しか読めず、10/24 20:00〜10/27 9:59 のお買い物マラソンを検知できなかった）
SALE_WINDOW = re.compile(r"(\d{1,2})/(\d{1,2})\s*(?:[(（][月火水木金土日][)）])?\s*(\d{1,2}):(\d{2})\s*[〜～~\-–ー]\s*"
                         r"(\d{1,2})/(\d{1,2})\s*(?:[(（][月火水木金土日][)）])?\s*(\d{1,2}):(\d{2})")


def _in_range(d: date, start: str, end: str) -> bool:
    try:
        return (datetime.fromisoformat(str(start)).date()
                <= d <= datetime.fromisoformat(str(end)).date())
    except (ValueError, TypeError):
        return False


def _event_signal(items: list[dict], now: datetime | None = None) -> tuple[float, int]:
    """(セール表記の割合, いま開催中の同じ期間を書いている「店の数」) を返す。

    2026-10-26 批判レビューを受けて:
    - 店の数で数える（adidas 1店の4商品だけで ×1.8 になる日があった）
    - 今日で終わる期間は数えない（10/27 9:59 終了のマラソンで、10/27 が丸1日 ×1.8 になるところだった）
    - 年をまたぐ期間（12/26〜1/5）は終わりを翌年として読む
    """
    if not items:
        return 0.0, 0
    now = now or datetime.now()
    names = [it.get("itemName", "") for it in items]
    kw_hit = sum(1 for n in names if EVENT_KEYWORDS.search(n))
    windows: dict[tuple, set] = {}
    for it in items:
        for m in SALE_WINDOW.finditer(it.get("itemName", "")):
            a = [int(x) for x in m.groups()]
            try:
                start = datetime(now.year, a[0], a[1], min(a[2], 23), a[3])
                end = datetime(now.year, a[4], a[5], min(a[6], 23), a[7])
                if end < start:  # 年をまたぐ
                    end = end.replace(year=end.year + 1)
                if start > now and (start - now).days > 180:  # 年初に前年12月の表記を読んだとき
                    start = start.replace(year=start.year - 1)
            except ValueError:
                continue
            if (end - start).days <= 10 and start <= now <= end and end.date() > now.date():
                shop = it.get("shopName") or (it.get("itemCode") or "").split(":")[0] or it.get("itemName", "")[:20]
                windows.setdefault((start, end), set()).add(shop)
    max_window = max((len(s) for s in windows.values()), default=0)
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
            reasons.append(f"セール開催中(同じ期間を書いている店{window_hits}店, ×{ev_mult})")

    cap = float(sb.get("max_multiplier", 2.0))
    return {"multiplier": round(min(multiplier, cap), 2), "reasons": reasons}
