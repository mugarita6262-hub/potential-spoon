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
FREEZE_AFTER_DAYS = 7

# よく使うRakutenジャンルIDの表示名
# （config.yamlのsources.ranking.genre_ids ＋ research.extra_genre_ids に対応）
GENRE_NAMES = {
    "0": "総合",
    "100939": "美容・コスメ・香水",
    "100804": "日用品雑貨・文房具・手芸",
    "100227": "食品",
    "558885": "スイーツ・お菓子",
    "101070": "家電",
    "100371": "レディースファッション",
    "551177": "メンズファッション",
    "216131": "キッズ・ベビー・マタニティ",
    "100533": "キッチン用品・食器",
    "100132": "ダイエット・健康",
    "101213": "スポーツ・アウトドア",
    "100026": "本・雑誌・コミック",
    "211742": "ペット・ペットグッズ",
    "101164": "インテリア・寝具・収納",
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
        if not post_id or rec.get("deleted"):
            continue
        try:
            posted_at = datetime.fromisoformat(rec["posted_at"])
        except (KeyError, ValueError):
            continue
        if now - posted_at < timedelta(hours=MIN_AGE_HOURS):
            continue
        # 表示回数は数日でほぼ止まる。古い投稿まで毎日取り直すと、Threads APIが遅い時に
        # 1回の集計が10分以上かかり、その間ほかのジョブが待たされるので打ち切る
        if rec.get("insights") and now - posted_at > timedelta(days=FREEZE_AFTER_DAYS):
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
            if "Unsupported get request" in str(exc):
                # 手動削除された投稿（二重投稿の片付け等）。以後は取りに行かず集計からも外す
                rec["deleted"] = True
                updated += 1
                continue
            print(f"  インサイト取得失敗（{rec.get('itemName', '')[:30]}）: {exc}")

    if updated:
        SNS_POSTED_FILE.write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return updated


def report_funnel(days: int = 14) -> dict:
    """フック投稿（PR無し）→ リプ欄のリンク投稿、に何割の人が進んでいるか。

    リンク投稿の閲覧数がフック投稿の閲覧数の何%か、をペアごとに出す。
    フック形式（2026-09-30〜）の効果を数字で追うための指標。
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    recs = [r for r in load_posted()
            if r.get("platform") == "threads" and r.get("insights") and not r.get("deleted")
            and r.get("posted_at", "") >= cutoff]
    hooks = {r["itemCode"][len("hook:"):]: r for r in recs if r.get("itemCode", "").startswith("hook:")}
    pairs = []
    for r in recs:
        hook = hooks.get(r.get("itemCode", ""))
        if not hook or r["posted_at"] < hook["posted_at"]:
            continue
        hv = int(hook["insights"].get("views") or 0)
        lv = int(r["insights"].get("views") or 0)
        pairs.append({"name": r.get("itemName", "")[:30], "posted_at": r["posted_at"],
                      "hook_views": hv, "link_views": lv,
                      # A/Bテスト開始(10/03)より前は全てツリー
                      "mode": r.get("link_mode") or "reply",
                      "rate": round(lv / hv * 100, 1) if hv else 0.0})

    def _rate(ps: list[dict]) -> float:
        hv_sum = sum(p["hook_views"] for p in ps)
        return round(sum(p["link_views"] for p in ps) / hv_sum * 100, 1) if hv_sum else 0.0

    by_mode = {}
    for mode in ("reply", "quote"):
        ps = [p for p in pairs if p["mode"] == mode]
        if ps:
            by_mode[mode] = {"count": len(ps), "rate": _rate(ps),
                             "avg_link_views": round(sum(p["link_views"] for p in ps) / len(ps), 1)}
    return {"pairs": sorted(pairs, key=lambda p: p["posted_at"]),
            "total_rate": _rate(pairs), "by_mode": by_mode}


def report_by_category() -> list[dict]:
    """category（Rakutenジャンル・A8プログラム等）別に平均反応を集計し、良い順に返す。"""
    buckets: dict[str, dict] = {}
    for rec in load_posted():
        insights = rec.get("insights")
        if not insights or rec.get("deleted"):
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
            "category_key": cat,  # 生のキー（Rakutenジャンルidの文字列 or A8のgenreタグ）
            "category": _label(cat),
            "count": n,
            "avg_likes": round(b["likes"] / n, 1),
            "avg_views": round(b["views"] / n, 1),
            "avg_reposts": round(b["reposts"] / n, 1),
            "sample": b["sample"],
        })
    rows.sort(key=lambda r: (r["avg_likes"], r["avg_views"]), reverse=True)
    return rows
