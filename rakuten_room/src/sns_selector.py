"""SNS（Threads等）向け: 値下がり・過去最安値の商品を選ぶ。"""
from __future__ import annotations

from . import price_history
from .sns_posted_log import recently_posted_keys


def select_sale_items(
    candidates: list[dict],
    top_n: int,
    min_discount_pct: float = 10.0,
    lookback_days: int = 30,
    cooldown_days: int = 30,
    platform: str = "threads",
) -> list[dict]:
    """値下がり・過去最安値の商品を上位 top_n 件選ぶ。

    候補全体の当日価格をまずスナップショット保存してから判定する
    （毎日呼ぶことで履歴が積み上がる）。
    """
    price_history.record_snapshot(candidates)

    skip = recently_posted_keys(cooldown_days, platform=platform)
    picked: list[dict] = []
    for it in candidates:
        key = it.get("itemCode") or it.get("itemUrl")
        if not key or key in skip:
            continue
        info = price_history.price_drop(it, lookback_days=lookback_days)
        if info["drop_pct"] < min_discount_pct and not info["is_all_time_low"]:
            continue
        picked.append({**it, **info})

    picked.sort(key=lambda x: (x["is_all_time_low"], x["drop_pct"]), reverse=True)
    return picked[:top_n]
