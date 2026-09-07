"""楽天ウェブサービス（商品検索・ランキング）クライアント。"""
from __future__ import annotations

import time
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse

import requests

# 2026年2月移行後の新エンドポイント（applicationId は UUID 形式 + accessKey が必須）
RANKING_URL = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"
SEARCH_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"


class RakutenAPI:
    def __init__(self, app_id: str, access_key: str = "", affiliate_id: str = "") -> None:
        if not app_id:
            raise RuntimeError(
                ".env の RAKUTEN_APP_ID が未設定です。"
                "https://webservice.rakuten.co.jp/ でアプリを作成し、"
                "アプリケーションID（UUID）とアクセスキーを取得してください。"
            )
        if not access_key:
            raise RuntimeError(
                ".env の RAKUTEN_ACCESS_KEY が未設定です。"
                "楽天ウェブサービスのアプリ詳細ページ『アクセスキー』の値を設定してください。"
            )
        self.app_id = app_id
        self.access_key = access_key
        self.affiliate_id = affiliate_id
        self.session = requests.Session()
        # アクセスキーは URL に出さずヘッダーで送る
        self.session.headers.update({"accessKey": access_key})

    def _get(self, url: str, params: dict) -> dict:
        params = {"applicationId": self.app_id, "format": "json", **params}
        if self.affiliate_id:
            params["affiliateId"] = self.affiliate_id
        for attempt in range(4):
            resp = self.session.get(url, params=params, timeout=20)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return {}

    def ranking(self, genre_id: int, count: int) -> list[dict]:
        """ジャンル別ランキング上位を返す。"""
        data = self._get(RANKING_URL, {"genreId": genre_id, "page": 1})
        items = [self._normalize(it["Item"]) for it in data.get("Items", [])]
        return items[:count]

    def search(self, keyword: str, count: int = 30, **extra) -> list[dict]:
        data = self._get(
            SEARCH_URL,
            {"keyword": keyword, "hits": min(count, 30), "page": 1,
             "sort": "-reviewCount", **extra},
        )
        return [self._normalize(it["Item"]) for it in data.get("Items", [])]

    def lookup_by_url(self, item_url: str) -> dict | None:
        """楽天商品URLから商品情報を1件引く（お気に入りリスト用）。"""
        code = _item_code_from_url(item_url)
        if code:
            data = self._get(SEARCH_URL, {"itemCode": code, "hits": 1})
        else:
            data = self._get(SEARCH_URL, {"keyword": item_url, "hits": 1})
        items = data.get("Items", [])
        return self._normalize(items[0]["Item"]) if items else None

    @staticmethod
    def _normalize(it: dict) -> dict:
        images = it.get("mediumImageUrls") or it.get("smallImageUrls") or []
        image = images[0]["imageUrl"].split("?")[0] if images else ""
        return {
            "itemCode": it.get("itemCode", ""),
            "itemName": it.get("itemName", ""),
            "itemUrl": _plain_item_url(it.get("itemUrl", "")),
            "affiliateUrl": it.get("affiliateUrl", ""),
            "price": int(it.get("itemPrice", 0) or 0),
            "shopName": it.get("shopName", ""),
            "genreId": str(it.get("genreId", "")),
            "reviewCount": int(it.get("reviewCount", 0) or 0),
            "reviewAverage": float(it.get("reviewAverage", 0) or 0),
            "pointRate": float(it.get("pointRate", 1) or 1),
            "rank": int(it.get("rank", 0) or 0),
            "imageUrl": image,
            "caption_hint": (it.get("catchcopy") or "").strip(),
        }


def _plain_item_url(url: str) -> str:
    """アフィリエイトのリダイレクトURLから素の item.rakuten.co.jp URL を取り出す。

    楽天ROOMは投稿時に自分のアフィリエイトリンクへ自動変換するので、
    投稿には素の商品URLを使う。
    """
    if not url:
        return url
    if "item.rakuten.co.jp" in url and "hb.afl.rakuten.co.jp" not in url:
        return url.split("?")[0]
    try:
        qs = parse_qs(urlparse(url).query)
        for key in ("pc", "url"):
            if key in qs:
                cand = unquote(qs[key][0])
                if "item.rakuten.co.jp" in cand:
                    return cand.split("?")[0]
    except (ValueError, KeyError, IndexError):
        pass
    return url


def _item_code_from_url(url: str) -> str:
    # 例: https://item.rakuten.co.jp/shop-name/item-id/  ->  shop-name:item-id
    try:
        parts = url.split("item.rakuten.co.jp/")[1].strip("/").split("/")
        if len(parts) >= 2:
            return f"{parts[0]}:{parts[1]}"
    except IndexError:
        pass
    return ""


def dedupe(items: Iterable[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        key = it.get("itemCode") or it.get("itemUrl")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
