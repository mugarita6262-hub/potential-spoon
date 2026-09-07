"""楽天市場のお気に入り商品を集める。

- data/favorites.txt に書いた商品URL（手動リスト）
- ログイン済みブラウザセッションでお気に入りページをスクレイプ（ベストエフォート）
"""
from __future__ import annotations

import re
from pathlib import Path

from .config import SESSION_DIR

ITEM_URL_RE = re.compile(r"https?://item\.rakuten\.co\.jp/[\w\-]+/[\w\-]+/?")


def _read_manual_list(path: str) -> list[str]:
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / path
    if not p.exists():
        return []
    urls = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            m = ITEM_URL_RE.search(line)
            if m:
                urls.append(m.group(0))
    return urls


def _scrape(url: str, limit: int = 60) -> list[str]:
    """お気に入りページから item.rakuten.co.jp のリンクを拾う。"""
    from playwright.sync_api import sync_playwright

    urls: list[str] = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR), headless=True
        )
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            # 遅延ロード対策に軽くスクロール
            for _ in range(4):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1200)
            for a in page.query_selector_all("a[href*='item.rakuten.co.jp']"):
                href = a.get_attribute("href") or ""
                m = ITEM_URL_RE.search(href)
                if m:
                    urls.append(m.group(0))
        except Exception as exc:  # noqa: BLE001
            print(f"  お気に入りページの取得に失敗: {exc}")
        finally:
            ctx.close()

    seen: set[str] = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:limit]


def collect_favorite_urls(fav_cfg: dict) -> list[str]:
    urls = _read_manual_list(fav_cfg.get("manual_list_file", "data/favorites.txt"))
    scraped = _scrape(fav_cfg["url"]) if fav_cfg.get("url") else []
    merged = urls + [u for u in scraped if u not in urls]
    if merged:
        print(f"  お気に入り候補: 手動 {len(urls)} 件 / スクレイプ {len(scraped)} 件")
    return merged
