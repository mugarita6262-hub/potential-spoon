"""お知らせページの構造を詳しく。タブ、アクティビティ行、フォローボタンの正体。
出力: data/explore_report.txt
"""
from __future__ import annotations

import json
from pathlib import Path

from src.poster import _launch, _safe_goto

OUT = Path(__file__).resolve().parent / "data" / "explore_report.txt"
SLUG = "room_e36e002876"

JS = r"""
() => {
  const vis = e => { const r=e.getBoundingClientRect(); return r.width>0 && r.height>0; };
  // タブらしき要素
  const tabs = Array.from(document.querySelectorAll('li,a,[role=tab],[ng-click]')).filter(vis)
    .map(e => ({ tag:e.tagName.toLowerCase(), text:(e.innerText||'').trim().slice(0,20),
                 ngClick:e.getAttribute('ng-click'), cls:(e.getAttribute('class')||'').slice(0,70) }))
    .filter(x => x.ngClick && /tab|show|activity|official|notification/i.test(x.ngClick));
  // 「さん」を含む行（アクティビティ）
  const rows = Array.from(document.querySelectorAll('li')).filter(vis)
    .filter(e => /さん.*(いいね|フォロー|コレ)/.test(e.innerText||''))
    .slice(0, 6).map(e => ({
      text: (e.innerText||'').replace(/\s+/g,' ').trim().slice(0,80),
      html: e.outerHTML.slice(0, 900),
    }));
  // follow クラスの要素の詳細（親も）
  const follows = Array.from(document.querySelectorAll('.follow, [class*=follow]')).filter(vis)
    .slice(0, 8).map(e => {
      const p = e.parentElement, pp = p && p.parentElement;
      return {
        self: {tag:e.tagName.toLowerCase(), text:(e.innerText||'').trim().slice(0,16),
               ngClick:e.getAttribute('ng-click'), cls:(e.getAttribute('class')||'').slice(0,70)},
        parent: p && {tag:p.tagName.toLowerCase(), ngClick:p.getAttribute('ng-click'),
                      cls:(p.getAttribute('class')||'').slice(0,70)},
        grand: pp && {tag:pp.tagName.toLowerCase(), ngClick:pp.getAttribute('ng-click'),
                      cls:(pp.getAttribute('class')||'').slice(0,70)},
      };
    });
  return { url: location.href, bodyHead: document.body.innerText.replace(/\s+/g,' ').slice(0,300),
           tabButtons: tabs.slice(0,15), activityRows: rows, followElems: follows };
}
"""


def main():
    pw, ctx, _b = _launch()
    L = []
    try:
        page = ctx.new_page()
        for url in [f"https://room.rakuten.co.jp/{SLUG}/notifications",
                    f"https://room.rakuten.co.jp/{SLUG}/notifications/activity",
                    f"https://room.rakuten.co.jp/notifications"]:
            _safe_goto(page, url)
            page.wait_for_timeout(5000)
            L.append("=" * 78); L.append(f"GOTO: {url}")
            try:
                L.append(json.dumps(page.evaluate(JS), ensure_ascii=False, indent=2))
            except Exception as e:
                L.append(f"  失敗: {e}")
        # notifications トップでタブを順にクリックして中身を見る
        _safe_goto(page, f"https://room.rakuten.co.jp/{SLUG}/notifications")
        page.wait_for_timeout(4000)
        for lb in ["あなた", "アクティビティ", "いいね", "コレ", "フォロー", "みんな"]:
            try:
                t = page.get_by_text(lb, exact=False).first
                if t.count() and t.is_visible():
                    t.click(timeout=3000); page.wait_for_timeout(3000)
                    L.append("=" * 78); L.append(f"タブ『{lb}』クリック後")
                    L.append(json.dumps(page.evaluate(JS), ensure_ascii=False, indent=2))
            except Exception as e:
                L.append(f"  タブ {lb}: {e}")
    finally:
        OUT.write_text("\n".join(L), encoding="utf-8")
        print("書き出しました:", OUT)
        pw.stop()


if __name__ == "__main__":
    main()
