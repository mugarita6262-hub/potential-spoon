"""「掲載終了商品を含む」トグルのDOMと、ON にしたときのカード数を調べる。
出力: data/explore_report.txt
"""
from __future__ import annotations

import json
from pathlib import Path

from src.pruner import _cards_now
from src.poster import _launch, _safe_goto

OUT = Path(__file__).resolve().parent / "data" / "explore_report.txt"
MY_ROOM = "https://room.rakuten.co.jp/room_e36e002876/items"

FIND_TOGGLE_JS = r"""
() => {
  const vis = e => { const r=e.getBoundingClientRect(); return r.width>0 && r.height>0; };
  const results = [];
  // 「掲載終了」を含むテキストノードの周辺を調べる
  const walker = document.evaluate("//*[contains(text(),'掲載終了')]", document, null,
    XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
  for (let i=0;i<walker.snapshotLength;i++){
    const el = walker.snapshotItem(i);
    let box = el;
    for (let k=0;k<3 && box.parentElement;k++) box = box.parentElement;
    results.push({
      text: (el.innerText||'').trim().slice(0,30),
      labelHTML: box.outerHTML.slice(0, 800),
    });
  }
  // 近くの input[type=checkbox] / role=switch / toggle クラス
  const toggles = Array.from(document.querySelectorAll(
    "input[type=checkbox], [role=switch], [class*=toggle i], [class*=switch i], label"))
    .filter(vis)
    .map(e => ({ tag:e.tagName.toLowerCase(), type:e.getAttribute('type'),
                 role:e.getAttribute('role'), cls:(e.getAttribute('class')||'').slice(0,80),
                 checked: e.checked, text:(e.innerText||'').trim().slice(0,24) }))
    .slice(0, 20);
  return { results, toggles };
}
"""


def main():
    pw, ctx, _b = _launch()
    L = []
    try:
        page = ctx.new_page()
        _safe_goto(page, MY_ROOM)
        page.wait_for_timeout(5000)
        for _ in range(3):
            page.mouse.wheel(0, 800); page.wait_for_timeout(800)

        L.append(f"トグルON前のカード数: {len(_cards_now(page))}")
        L.append(json.dumps(page.evaluate(FIND_TOGGLE_JS), ensure_ascii=False, indent=2))

        # クリックを試す
        L.append("\n=== 『掲載終了商品を含む』をクリック試行 ===")
        for sel in [
            'text=掲載終了商品を含む',
            'label:has-text("掲載終了")',
            ':near(:text("掲載終了商品を含む"))',
        ]:
            try:
                loc = page.locator(sel).first
                if loc.count():
                    loc.click(timeout=4000)
                    L.append(f"  クリック成功: {sel}")
                    page.wait_for_timeout(4000)
                    break
            except Exception as e:
                L.append(f"  {sel}: {e}")
        else:
            # テキストの隣にあるトグルらしき要素をクリック
            try:
                page.get_by_text("掲載終了商品を含む").locator("xpath=following::*[1]").click(timeout=4000)
                L.append("  隣接要素クリック成功")
                page.wait_for_timeout(4000)
            except Exception as e:
                L.append(f"  隣接クリック失敗: {e}")

        for _ in range(3):
            page.mouse.wheel(0, 1500); page.wait_for_timeout(1000)
        L.append(f"\nトグル操作後のカード数: {len(_cards_now(page))}")
        L.append(f"URL: {page.url}")
    finally:
        OUT.write_text("\n".join(L), encoding="utf-8")
        print("書き出しました:", OUT)
        pw.stop()


if __name__ == "__main__":
    main()
