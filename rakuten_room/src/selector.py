"""候補を集めて、スコア上位 N 件を選ぶ。"""
from __future__ import annotations

import json
import random

from .config import DATA_DIR
from .favorites import collect_favorite_urls
from .posted_log import recently_posted_keys
from .rakuten_api import RakutenAPI, dedupe
from .scoring import score_items


def gather_candidates(cfg: dict, api: RakutenAPI) -> list[dict]:
    candidates: list[dict] = []
    sources = cfg["sources"]

    if sources["ranking"]["enabled"]:
        for genre_id in sources["ranking"]["genre_ids"]:
            try:
                items = api.ranking(int(genre_id), sources["ranking"]["per_genre"])
                _log_ranking(items)
                candidates.extend(items)
                print(f"  ランキング genre={genre_id}: {len(items)} 件")
            except Exception as exc:  # noqa: BLE001
                print(f"  ランキング genre={genre_id} 失敗: {exc}")

    kw = sources.get("keywords") or {}
    if kw.get("enabled"):
        for word in kw.get("words", []):
            try:
                # 毎日同じ商品にならないよう、検索結果のページをランダムに選ぶ
                items = api.search(word, int(kw.get("per_keyword", 30)), sort="standard",
                                   page=random.randint(1, 10))
                candidates.extend(items)
                print(f"  キーワード「{word}」: {len(items)} 件")
            except Exception as exc:  # noqa: BLE001
                print(f"  キーワード「{word}」失敗: {exc}")

    rs = sources.get("room_search") or {}
    if rs.get("enabled"):
        candidates.extend(_room_hot_items(rs, api))

    if sources["favorites"]["enabled"]:
        fav_urls = collect_favorite_urls(sources["favorites"])
        for url in fav_urls:
            try:
                it = api.lookup_by_url(url)
                if it:
                    candidates.append(it)
            except Exception as exc:  # noqa: BLE001
                print(f"  お気に入り {url} 取得失敗: {exc}")

    from .claims_filter import drop_risky

    return drop_risky(dedupe(candidates))


def _room_hot_items(rs: dict, api: RakutenAPI) -> list[dict]:
    """楽天ROOMの中で反応が出ている商品（2026-10-15 追加）。

    以前使っていたツール（ROOM REPEAT 極）は、ROOM内をキーワード検索して他の人が投稿している商品を
    コレ！していた。ROOMの利用者が実際に反応している商品なので売れやすい。ここでは商品だけを借り、
    紹介文は自分で書く（他人の文章は使わない）。ROOMの検索APIはログイン不要。
    """
    import time

    import requests

    words = list(rs.get("words") or [])
    random.shuffle(words)
    words = words[: int(rs.get("per_run_words", 6))]
    min_likes = int(rs.get("min_likes", 300))
    keys: dict[str, str] = {}
    for w in words:
        for pg in range(1, int(rs.get("pages", 2)) + 1):
            try:
                r = requests.get("https://room.rakuten.co.jp/api/collect/search", timeout=20,
                                 headers={"User-Agent": "Mozilla/5.0"},
                                 params={"api_version": 1, "currentTab": "collect", "item_page": pg,
                                         "keyword": w, "page": pg, "query": w})
                data = r.json().get("data") or []
            except Exception as exc:  # noqa: BLE001
                print(f"  ROOM検索「{w}」失敗: {exc}")
                break
            for c in data:
                it = c.get("item") or {}
                if it.get("flg_soldout") or it.get("flg_deleted") or not it.get("url"):
                    continue
                # 他の人もコレ！している（recollects）か、いいねが多いものだけ
                if (int(c.get("recollects") or 0) >= 1 or int(c.get("likes") or 0) >= min_likes) and it.get("key"):
                    keys.setdefault(it["key"], w)
            time.sleep(1.0)
    out = []
    for code in list(keys)[: int(rs.get("max_items", 40))]:
        try:
            it = api.lookup_by_code(code)
        except Exception:  # noqa: BLE001
            it = None
        if it:
            it["rank"] = 1  # ROOMで反応がある＝人気の目印として、スコアでランキング上位と同じ扱いにする
            it["source"] = "room"
            out.append(it)
    print(f"  ROOMで反応がある商品（{'・'.join(words)}）: {len(out)} 件")
    return out


RANKING_LOG = DATA_DIR / "ranking_log.json"
SALE_RE = __import__("re").compile(r"クーポン|[0-9０-９]+\s*[%％]\s*OFF|[0-9０-９]+\s*[%％]オフ|半額|ポイント\s*[0-9０-９]+\s*倍|P\s*[0-9０-９]+\s*倍|"
                                    r"タイムセール|スーパーSALE|SALE|セール|値下げ|期間限定価格|特価", __import__("re").I)


def _log_ranking(items: list[dict]) -> None:
    """楽天ランキングに入った商品を日ごとに記録（何日ランクインし続けたかで「定番の売れ筋」を判定するため）。"""
    from datetime import date
    try:
        log = json.loads(RANKING_LOG.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        log = {}
    day = log.setdefault(date.today().isoformat(), {})
    for it in items:
        code = it.get("itemCode")
        if code and it.get("rank", 0) > 0:
            day[code] = min(day.get(code, 999), it["rank"])
    for k in sorted(log)[:-60]:  # 60日分だけ残す
        del log[k]
    RANKING_LOG.write_text(json.dumps(log, ensure_ascii=False), encoding="utf-8")


def ranking_days(within: int = 30) -> dict[str, int]:
    """直近 within 日のうち、楽天ランキングに入っていた日数（商品コードごと）。"""
    try:
        log = json.loads(RANKING_LOG.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    out: dict[str, int] = {}
    for day in sorted(log)[-within:]:
        for code in log[day]:
            out[code] = out.get(code, 0) + 1
    return out


def is_evergreen(it: dict, days: dict[str, int], ev: dict) -> bool:
    """ほっといても売れる定番：レビューが非常に多く評価も高い商品がランキングに入っている、
    または直近30日で何日もランキングに入り続けている。"""
    if days.get(it.get("itemCode", ""), 0) >= int(ev.get("min_rank_days", 7)):
        return True
    return (it.get("rank", 0) > 0 and it.get("reviewCount", 0) >= int(ev.get("min_reviews", 5000))
            and it.get("reviewAverage", 0) >= float(ev.get("min_average", 4.3)))


def select_items(cfg: dict, api: RakutenAPI, pool: int | None = None) -> list[dict]:
    candidates = gather_candidates(cfg, api)
    print(f"重複除去後の候補: {len(candidates)} 件")

    ev = cfg.get("evergreen") or {}
    days = ranking_days()
    for it in candidates:
        it["evergreen"] = is_evergreen(it, days, ev)
    skip = recently_posted_keys(cfg["exclude"]["reposted_within_days"])
    # 定番の売れ筋は、前回から repost_after_days 日たてばもう一度投稿する（売れ続けている商品なので）
    skip_ev = recently_posted_keys(int(ev.get("repost_after_days", 21)))
    candidates = [
        it for it in candidates
        if (it.get("itemCode") or it.get("itemUrl")) not in (skip_ev if it["evergreen"] else skip)
    ]
    print(f"投稿済みを除外後: {len(candidates)} 件（うち定番の売れ筋 {sum(it['evergreen'] for it in candidates)} 件）")

    ranked = score_items(candidates, cfg["scoring"])
    bonus = float(ev.get("score_bonus", 0.15))
    sale_bonus = float((cfg.get("sale_boost") or {}).get("bonus", 0))
    for it in ranked:
        if it.get("evergreen"):
            it["score"] = round(it["score"] + bonus, 4)
        # 商品名の先頭にクーポン・割引・ポイント倍などがある＝いまセールでお得な商品
        if sale_bonus and SALE_RE.search((it.get("itemName") or "")[:60]):
            it["on_sale"] = True
            it["score"] = round(it["score"] + sale_bonus, 4)
    ranked.sort(key=lambda x: x["score"], reverse=True)
    print(f"スコア条件を満たした候補: {len(ranked)} 件")

    if pool is None:
        pool = int(cfg.get("candidate_pool", cfg["post_count"] * 3))
    return ranked[:pool]
