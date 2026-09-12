"""SNS拡散用: 商品の価格履歴を保存し、値下がり・過去最安値を検知する。

毎日 `sns` コマンド実行時に、その日集めた候補（ランキング＋お気に入り）の価格を
1商品1日1件スナップショットしていく。日々の記録が積み上がるほど値下がり判定の精度が上がる
（初日〜数日は比較対象が無く drop_pct=0 になるのが正常）。
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from .config import DATA_DIR

HISTORY_FILE = DATA_DIR / "price_history.json"
KEEP_DAYS = 90


def _load() -> dict[str, list[dict]]:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save(data: dict[str, list[dict]]) -> None:
    HISTORY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def record_snapshot(items: list[dict]) -> None:
    """候補商品の当日価格を記録する（1商品1日1件、直近 KEEP_DAYS 日分だけ保持）。"""
    today = date.today().isoformat()
    cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    data = _load()
    for it in items:
        key = it.get("itemCode") or it.get("itemUrl")
        price = it.get("price")
        if not key or not price:
            continue
        rows = data.setdefault(key, [])
        if rows and rows[-1]["date"] == today:
            rows[-1]["price"] = price  # 同日に複数回実行された場合は上書き
        else:
            rows.append({"date": today, "price": price})
        data[key] = [r for r in rows if r["date"] >= cutoff]
    _save(data)


def price_drop(item: dict, lookback_days: int = 30) -> dict:
    """値下がり情報を返す。

    {"drop_pct": 直近参考価格からの下落率(%), "reference_price": 参考にした価格,
     "is_all_time_low": 記録上の過去最安値か}

    履歴が無い（今日が初回）場合は drop_pct=0 / is_all_time_low=False。
    """
    key = item.get("itemCode") or item.get("itemUrl")
    price = int(item.get("price", 0) or 0)
    today = date.today().isoformat()
    rows = _load().get(key, [])
    past = [r["price"] for r in rows if r["date"] != today]

    if not past or not price:
        return {"drop_pct": 0.0, "reference_price": price, "is_all_time_low": False}

    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    recent = [r["price"] for r in rows if r["date"] != today and r["date"] >= cutoff]
    reference = max(recent or past)
    drop_pct = round((reference - price) / reference * 100, 1) if reference else 0.0

    return {
        "drop_pct": max(drop_pct, 0.0),
        "reference_price": reference,
        "is_all_time_low": price <= min(past),
    }
