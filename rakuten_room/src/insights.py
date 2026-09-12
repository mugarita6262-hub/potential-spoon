"""Threads投稿の反応（インサイト）を取得し、ジャンル・商品別に集計する。

「どんな商品・ジャンルが反応いいか」を見るためのもの。実際の収益（アフィリ成果）
とは別軸の指標だが、成果データが貯まるまでの先行指標として使う。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .sns_posted_log import SNS_POSTED_FILE, load_posted
from .threads_poster import get_media_insights

# 投稿直後は数値が安定しないので、これより古い投稿だけ対象にする
MIN_AGE_HOURS = 24
# 一度取得したら、この時間内は再取得しない（無駄なAPI呼び出しを避ける）
RESYNC_AFTER_HOURS = 24

# よく使うRakutenジャンルIDの表示名（config.yamlのsources.ranking.genre_idsに対応）
GENRE_NAMES = {
    "0": "総合",
    "100939": "美容・コスメ・香水",
    "100804": "日用品雑貨・文房具・手芸",
    "100227": "食品",
    "558885": "スイーツ・お菓子",
}


def _label(category: str) -> str:
    return GENRE_NAMES.get(category, category or "不明")


def sync_insights(access_token: str) -> int:
    """post_idがある投稿のうち、対象になるものにインサイトを取得・追記する。更新件数を返す。"""
    log = load_posted()
    now = datetime.now()
    updated = 0
    for rec in log:
        post_id = rec.get("post_id")
        if not post_id:
            continue
        try:
            posted_at = datetime.fromisoformat(rec["posted_at"])
        except (KeyError, ValueError):
            continue
        if now - posted_at < timedelta(hours=MIN_AGE_HOURS):
            continue
        synced_at = rec.get("insights_synced_at")
        if synced_at:
            try:
                if now - datetime.fromisoformat(synced_at) < timedelta(hours=RESYNC_AFTER_HOURS):
                    continue
            except ValueError:
                pass
        try:
            rec["insights"] = get_media_insights(access_token, post_id)
            rec["insights_synced_at"] = now.isoformat(timespec="seconds")
            updated += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  インサイト取得失敗（{rec.get('itemName', '')[:30]}）: {exc}")

    if updated:
        SNS_POSTED_FILE.write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return updated


def report_by_category() -> list[dict]:
    """category（Rakutenジャンル・A8プログラム等）別に平均反応を集計し、良い順に返す。"""
    buckets: dict[str, dict] = {}
    for rec in load_posted():
        insights = rec.get("insights")
        if not insights:
            continue
        cat = rec.get("category") or "不明"
        b = buckets.setdefault(cat, {"count": 0, "likes": 0, "views": 0,
                                      "reposts": 0, "sample": rec.get("itemName", "")})
        b["count"] += 1
        b["likes"] += int(insights.get("likes") or 0)
        b["views"] += int(insights.get("views") or 0)
        b["reposts"] += int(insights.get("reposts") or 0)

    rows = []
    for cat, b in buckets.items():
        n = b["count"]
        rows.append({
            "category": _label(cat),
            "count": n,
            "avg_likes": round(b["likes"] / n, 1),
            "avg_views": round(b["views"] / n, 1),
            "avg_reposts": round(b["reposts"] / n, 1),
            "sample": b["sample"],
        })
    rows.sort(key=lambda r: (r["avg_likes"], r["avg_views"]), reverse=True)
    return rows
