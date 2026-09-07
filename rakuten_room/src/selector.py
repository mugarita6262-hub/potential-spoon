"""候補を集めて、スコア上位 N 件を選ぶ。"""
from __future__ import annotations

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
                candidates.extend(items)
                print(f"  ランキング genre={genre_id}: {len(items)} 件")
            except Exception as exc:  # noqa: BLE001
                print(f"  ランキング genre={genre_id} 失敗: {exc}")

    if sources["favorites"]["enabled"]:
        fav_urls = collect_favorite_urls(sources["favorites"])
        for url in fav_urls:
            try:
                it = api.lookup_by_url(url)
                if it:
                    candidates.append(it)
            except Exception as exc:  # noqa: BLE001
                print(f"  お気に入り {url} 取得失敗: {exc}")

    return dedupe(candidates)


def select_items(cfg: dict, api: RakutenAPI) -> list[dict]:
    candidates = gather_candidates(cfg, api)
    print(f"重複除去後の候補: {len(candidates)} 件")

    skip = recently_posted_keys(cfg["exclude"]["reposted_within_days"])
    candidates = [
        it for it in candidates
        if (it.get("itemCode") or it.get("itemUrl")) not in skip
    ]
    print(f"投稿済みを除外後: {len(candidates)} 件")

    ranked = score_items(candidates, cfg["scoring"])
    print(f"スコア条件を満たした候補: {len(ranked)} 件")

    pool = int(cfg.get("candidate_pool", cfg["post_count"] * 3))
    return ranked[:pool]
