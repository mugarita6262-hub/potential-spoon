"""お知らせのアクティビティ行1つで、名前の場所とフォロー後の変化を調べる。
※ 1件だけ実際にフォローする。
出力: data/explore_report.txt
"""
from __future__ import annotations

import json
from pathlib import Path

from src.poster import _launch, _safe_goto

OUT = Path(__file__).resolve().parent / "data" / "explore_report.txt"
SLUG = "room_e36e002876"

ROW_JS = r"""
() => {
  const rows = Array.from(document.querySelectorAll('li')).filter(li => {
    const s = li.querySelector('span.follow');
    return s && /未フォロー/.test(s.innerText||'');
  });
  return rows.slice(0, 4).map(li => ({
    innerText: (li.innerText||'').replace(/\s+/g,' ').trim().slice(0,120),
    ngRepeat: li.getAttribute('ng-repeat'),
    cls: (li.getAttribute('class')||'').slice(0,60),
    nameCandidates: {
      strong: (li.querySelector('.strong')||{}).innerText,
      noticeName: (li.querySelector('.notice-name')||{}).innerText,
      firstA: (li.querySelector('a')||{}).getAttribute && li.querySelector('a').getAttribute('href'),
    },
    followSpan: {
      text: (li.querySelector('span.follow')||{}).innerText,
      cls: (li.querySelector('span.follow')||{}).className,
      parentCls: (li.querySelector('span.follow')||{}).parentElement.className,
    },
    html: li.outerHTML.slice(0, 1100),
  }));
}
"""


def main():
    pw, ctx, _b = _launch()
    L = []
    try:
        page = ctx.new_page()
        _safe_goto(page, f"https://room.rakuten.co.jp/{SLUG}/notifications")
        page.wait_for_timeout(5000)
        for _ in range(4):
            page.mouse.wheel(0, 2200); page.wait_for_timeout(1000)

        L.append("=== フォロー前 ===")
        before = page.evaluate(ROW_JS)
        L.append(json.dumps(before, ensure_ascii=False, indent=2))

        if before:
            L.append("\n=== 1行目の span.follow をクリック ===")
            try:
                # 1つ目の 未フォロー 行の span.follow
                sp = page.locator('li:has(span.follow) span.follow').filter(
                    has_text="未フォロー").first
                sp.scroll_into_view_if_needed(timeout=4000)
                sp.click(timeout=5000)
                page.wait_for_timeout(4000)
                L.append("クリック成功")
            except Exception as e:
                L.append(f"クリック失敗: {e}")

            L.append("\n=== フォロー後 ===")
            L.append(json.dumps(page.evaluate(ROW_JS), ensure_ascii=False, indent=2))
    finally:
        OUT.write_text("\n".join(L), encoding="utf-8")
        print("書き出しました:", OUT)
        pw.stop()


if __name__ == "__main__":
    main()
