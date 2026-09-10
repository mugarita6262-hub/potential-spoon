"""ROOMのフィード（新着）・いいねボタン・フォローボタン・お知らせの構造を調べる。
出力: data/explore_report.txt
"""
from __future__ import annotations

import json
from pathlib import Path

from src.poster import _launch, _safe_goto

OUT = Path(__file__).resolve().parent / "data" / "explore_report.txt"

URLS = [
    "https://room.rakuten.co.jp/",
    "https://room.rakuten.co.jp/items",
    "https://room.rakuten.co.jp/myfollow/feed",
    "https://room.rakuten.co.jp/search/item?sort=new",
    "https://room.rakuten.co.jp/room_e36e002876/notifications",
]

SCAN_JS = r"""
() => {
  const vis = e => { const r=e.getBoundingClientRect(); return r.width>0 && r.height>0; };
  const btns = Array.from(document.querySelectorAll('button,a,[role=button],[ng-click],[class*=like i],[class*=follow i],[class*=iine i]'))
    .filter(vis)
    .map(e => ({ tag:e.tagName.toLowerCase(), text:(e.innerText||'').trim().slice(0,16),
                 aria:e.getAttribute('aria-label'), ngClick:e.getAttribute('ng-click'),
                 cls:(e.getAttribute('class')||'').slice(0,90) }))
    .filter(b => /like|follow|iine|いいね|フォロー|♡|ハート/i.test(
        (b.text||'')+(b.aria||'')+(b.ngClick||'')+(b.cls||'')));
  const cards = Array.from(document.querySelectorAll('[class*=collect i],[class*=feed i],[class*=item i],li,article'))
    .filter(vis).filter(e => e.querySelector('img') && /いいね|♡|like/i.test(e.innerText||''))
    .slice(0,2).map(e => e.outerHTML.slice(0,1400));
  return {
    url: location.href, title: document.title,
    bodyHead: document.body.innerText.replace(/\s+/g,' ').slice(0, 400),
    likeFollowButtons: btns.slice(0, 25),
    cardSample: cards,
  };
}
"""


def main():
    pw, ctx, _b = _launch()
    L = []
    try:
        page = ctx.new_page()
        for url in URLS:
            _safe_goto(page, url)
            page.wait_for_timeout(5000)
            for _ in range(2):
                page.mouse.wheel(0, 1600); page.wait_for_timeout(900)
            L.append("=" * 78)
            L.append(f"GOTO: {url}")
            try:
                L.append(json.dumps(page.evaluate(SCAN_JS), ensure_ascii=False, indent=2))
            except Exception as e:
                L.append(f"  失敗: {e}")
    finally:
        OUT.write_text("\n".join(L), encoding="utf-8")
        print("書き出しました:", OUT)
        pw.stop()


if __name__ == "__main__":
    main()
