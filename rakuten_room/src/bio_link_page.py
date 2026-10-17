"""Instagramで紹介した商品を data/ig_bio_cache.json に記録する（買い時ナビの「Instagramで紹介中」帯が読む）。

2026-10-16 にプロフィールのリンクを買い時ナビへ変えた。以前のリンクインバイオページ
（/home/kirui/privacy_page/links/）は、買い時ナビへ転送するだけの静的ページとしてサーバーに残してある。
"""
from __future__ import annotations


def recent_instagram_items(api, n: int = 12) -> list[dict]:
    """sns_posted.json のInstagram投稿から、まとめページに出す商品情報を作る（アフィリリンク・画像・価格）。
    楽天APIで引いた結果は data/ig_bio_cache.json に残して、毎回引き直さない。"""
    import json
    from .config import DATA_DIR
    from .sns_posted_log import load_posted
    cache_file = DATA_DIR / "ig_bio_cache.json"
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        cache = {}
    posts = [x for x in load_posted() if x.get("platform") == "instagram" and x.get("itemCode")][::-1]
    out, seen = [], set()
    for x in posts:
        code = x["itemCode"]
        if code in seen:
            continue
        seen.add(code)
        if code not in cache:
            try:
                it = api.lookup_by_code(code)
            except Exception:  # noqa: BLE001
                it = None
            cache[code] = ({"name": it["itemName"], "url": it.get("affiliateUrl") or it["itemUrl"],
                            "img": it.get("imageUrl", ""), "price": it.get("price", 0)} if it else {})
        if cache[code]:
            out.append({**cache[code], "posted_at": x.get("posted_at", "")})
        if len(out) >= n:
            break
    cache_file.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return out

