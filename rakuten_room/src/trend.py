"""ジャンル単位の価格トレンド（直近N日間の平均価格変化）を計算する。

sns（個別商品の値下がり検知）と違い、ジャンル全体の傾向なので出現条件が緩く、
`collect`で貯まった価格履歴さえあれば毎回何かしら計算できる＝投稿ネタになりやすい。
"""
from __future__ import annotations

from datetime import date, timedelta

from . import price_history


def genre_trend(candidates: list[dict], lookback_days: int = 7,
                 min_sample: int = 3) -> list[dict]:
    """candidates（現在のジャンルID付き商品リスト）から、ジャンルごとの
    直近lookback_days日間の平均価格変化率を計算し、変化が大きい順に返す。

    [{"genre_id": str, "pct_change": float, "direction": "値下がり"|"値上がり",
      "count": int}]
    """
    history = price_history.load_all()
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    today = date.today().isoformat()

    by_genre: dict[str, list[tuple[float, float]]] = {}
    for it in candidates:
        genre_id = str(it.get("genreId", "") or "")
        key = it.get("itemCode") or it.get("itemUrl")
        now_price = it.get("price")
        if not genre_id or not key or not now_price:
            continue

        rows = history.get(key, [])
        past_rows = [r for r in rows if cutoff <= r["date"] < today]
        if not past_rows:
            continue
        past_price = past_rows[0]["price"]  # 期間内で一番古い記録
        if not past_price:
            continue
        by_genre.setdefault(genre_id, []).append((past_price, now_price))

    results: list[dict] = []
    for genre_id, pairs in by_genre.items():
        if len(pairs) < min_sample:
            continue
        past_avg = sum(p for p, _ in pairs) / len(pairs)
        now_avg = sum(n for _, n in pairs) / len(pairs)
        if past_avg <= 0:
            continue
        pct_change = (now_avg - past_avg) / past_avg * 100
        results.append({
            "genre_id": genre_id,
            "pct_change": round(pct_change, 1),
            "direction": "値下がり" if pct_change < 0 else "値上がり",
            "count": len(pairs),
        })

    results.sort(key=lambda r: abs(r["pct_change"]), reverse=True)
    return results
