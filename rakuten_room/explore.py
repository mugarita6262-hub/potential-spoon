"""『削除』ボタンを押したとき、ブラウザ標準ダイアログが出るか / DOMダイアログか / 何も無いかを調べる。
※ ダイアログは打ち消す（dismiss）ので実際には削除しない。
出力: data/explore_report.txt
"""
from __future__ import annotations

import json
from pathlib import Path

from src.poster import _launch, _safe_goto

OUT = Path(__file__).resolve().parent / "data" / "explore_report.txt"
MY_ROOM = "https://room.rakuten.co.jp/room_e36e002876/items"


def main():
    pw, ctx, _b = _launch()
    lines = []
    dialog_events = []
    try:
        page = ctx.new_page()

        def on_dialog(d):
            dialog_events.append({"type": d.type, "message": d.message})
            try:
                d.dismiss()  # 実削除しないよう必ずキャンセル
            except Exception:  # noqa: BLE001
                pass

        page.on("dialog", on_dialog)

        _safe_goto(page, MY_ROOM)
        page.wait_for_timeout(5000)
        for _ in range(4):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1000)

        # 売切れ投稿を探す
        imgs = page.locator("img")
        target_url = None
        for i in range(min(imgs.count(), 40)):
            el = imgs.nth(i)
            try:
                box = el.bounding_box()
                if not box or box["width"] < 110 or box["y"] < 150:
                    continue
                el.scroll_into_view_if_needed(timeout=3000)
                el.click(timeout=4000)
                page.wait_for_timeout(3000)
            except Exception:  # noqa: BLE001
                continue
            info = page.evaluate(
                "() => ({soldout: document.body.innerText.includes('売切れ'),"
                " hasDel: !!document.querySelector('button[aria-label=\"削除\"]'), url: location.href})"
            )
            if info["soldout"] and info["hasDel"]:
                target_url = info["url"]
                break
            _safe_goto(page, MY_ROOM)
            page.wait_for_timeout(3000)
            for _ in range(3):
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(800)

        if not target_url:
            lines.append("売切れ投稿が見つかりませんでした")
        else:
            lines.append(f"対象の売切れ投稿: {target_url}")
            page.wait_for_timeout(1000)

            before = page.evaluate("() => document.querySelectorAll('*').length")
            lines.append("『削除』ボタンをクリックします...")
            page.locator('button[aria-label="削除"]').first.click(timeout=5000)
            page.wait_for_timeout(3500)

            lines.append(f"\nネイティブダイアログ発生: {json.dumps(dialog_events, ensure_ascii=False)}")

            after = page.evaluate(r"""
            () => {
              const vis = e => { const r=e.getBoundingClientRect(); return r.width>0&&r.height>0; };
              const cand = Array.from(document.querySelectorAll('div,section,[role=dialog],[role=alertdialog]'))
                .filter(vis)
                .filter(e => /削除|本当に|よろしい|できません|OK|はい|いいえ/.test(e.innerText||''))
                .filter(e => (e.innerText||'').length < 200)
                .map(e => ({ cls:(e.getAttribute('class')||'').slice(0,120),
                             text:(e.innerText||'').replace(/\s+/g,' ').trim().slice(0,160),
                             html:e.outerHTML.slice(0,600) }));
              const btns = Array.from(document.querySelectorAll('button,a,[ng-click]'))
                .filter(vis)
                .filter(e => /削除|OK|はい|いいえ|キャンセル|とじる|閉じる/.test((e.innerText||'')))
                .map(e => ({ tag:e.tagName.toLowerCase(), text:(e.innerText||'').trim().slice(0,20),
                             ngClick:e.getAttribute('ng-click'), cls:(e.getAttribute('class')||'').slice(0,90) }));
              return { url: location.href, elemCount: document.querySelectorAll('*').length,
                       dialogCandidates: cand, buttons: btns,
                       bodyChunk: document.body.innerText.replace(/\s+/g,' ').slice(0,400) };
            }
            """)
            lines.append(f"DOM要素数 before={before} after={after['elemCount']}")
            lines.append(json.dumps(after, ensure_ascii=False, indent=2))
    finally:
        OUT.write_text("\n".join(lines), encoding="utf-8")
        print("書き出しました:", OUT)
        pw.stop()


if __name__ == "__main__":
    main()
