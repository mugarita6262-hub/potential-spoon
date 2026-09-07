"""候補商品を「売れそう」順にスコアリングする。"""
from __future__ import annotations

import math


def _norm(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _price_fit(price: int, band: list[int]) -> float:
    lo, hi = band
    if price <= 0:
        return 0.0
    if lo <= price <= hi:
        return 1.0
    if price < lo:
        return max(0.0, price / lo)
    # 高いほど緩やかに減衰
    return max(0.0, 1.0 - math.log10(price / hi))


def score_items(items: list[dict], scoring_cfg: dict) -> list[dict]:
    if not items:
        return []

    w = scoring_cfg["weights"]
    band = scoring_cfg["price_band"]
    min_reviews = scoring_cfg["min_review_count"]
    min_avg = scoring_cfg["min_review_average"]

    kept = [
        it for it in items
        if it["reviewCount"] >= min_reviews and it["reviewAverage"] >= min_avg
    ]
    if not kept:
        return []

    max_reviews = max(it["reviewCount"] for it in kept)
    # log スケール（レビュー件数は桁で効く）
    log_max = math.log10(max_reviews + 1) or 1.0
    max_point = max((it["pointRate"] for it in kept), default=1.0)
    ranks = [it["rank"] for it in kept if it["rank"] > 0]
    worst_rank = max(ranks) if ranks else 1

    for it in kept:
        s_reviews = math.log10(it["reviewCount"] + 1) / log_max
        s_avg = _norm(it["reviewAverage"], min_avg, 5.0)
        s_rank = (1.0 - it["rank"] / worst_rank) if it["rank"] > 0 else 0.4
        s_price = _price_fit(it["price"], band)
        s_point = _norm(it["pointRate"], 1.0, max_point) if max_point > 1 else 0.0

        it["score"] = round(
            w["review_count"] * s_reviews
            + w["review_average"] * s_avg
            + w["ranking_rank"] * s_rank
            + w["price_fit"] * s_price
            + w["point_rate"] * s_point,
            4,
        )
        it["score_breakdown"] = {
            "reviews": round(s_reviews, 2),
            "avg": round(s_avg, 2),
            "rank": round(s_rank, 2),
            "price": round(s_price, 2),
            "point": round(s_point, 2),
        }

    kept.sort(key=lambda x: x["score"], reverse=True)
    return kept
