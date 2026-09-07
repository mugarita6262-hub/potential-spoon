"""上限対策: 自分のROOMの古い / 売切れ投稿を削除して空きを作る。

mode="oldest"  : 一覧の先頭（古い投稿）から順に削除
mode="soldout" : 売切れ投稿だけ削除（反応なしを優先）

only_before ガード: その日付より後の投稿は削除しない。
commit=False（プレビュー）では削除しない。
削除は confirm ダイアログ（この商品を削除してよろしいですか？）を自動承認。
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR
from .poster import _launch, _safe_goto

PRUNE_LOG = DATA_DIR / "pruned.json"
PREVIEW_FILE = DATA_DIR / "prune_preview.json"

DETAIL_RE = re.compile(r"/room_[0-9a-z]+/(\d{6,})")
NEXT_SEL = 'button[aria-label="swipe-right"]'
DEL_SEL = 'button[aria-label="削除"]'

DETAIL_JS = r"""
() => {
  const bodyText = document.body.innerText;
  const cut = bodyText.indexOf('削除 編集');
  const head = cut > 0 ? bodyText.slice(0, cut) : bodyText.slice(0, 600);
  const likeM = bodyText.match(/いいね\((\d+)人\)/);
  const cmtM = bodyText.match(/コメント\((\d+)件\)/);
  const dateM = bodyText.match(/(20\d\d)年(\d\d?)月(\d\d?)日に投稿されました/);
  return {
    hasDelete: !!document.querySelector('button[aria-label="削除"]'),
    soldOut: /売切れ|販売[を]?(終了|停止)|お取り扱いが終了/.test(head),
    likes: likeM ? parseInt(likeM[1], 10) : null,
    comments: cmtM ? parseInt(cmtM[1], 10) : null,
    postedYmd: dateM ? `${dateM[1]}-${String(dateM[2]).padStart(2,'0')}-${String(dateM[3]).padStart(2,'0')}` : null,
    name: head.replace(/\s+/g,' ').trim().slice(-110),
  };
}
"""


def _load(path, default):
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return default
    return default


def _save(path, data) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _pid(s: str) -> str:
    m = DETAIL_RE.search(s or "")
    return m.group(1) if m else ""


LOAD_MORE_LABELS = ["さらに読み込む", "もっと見る", "続きを見る", "もっと読み込む"]


def _click_load_more(page) -> bool:
    for lb in LOAD_MORE_LABELS:
        try:
            b = page.get_by_text(lb, exact=False).first
            if b.count() and b.is_visible():
                b.scroll_into_view_if_needed(timeout=3000)
                b.click(timeout=4000)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _thumbs_now(page) -> list:
    thumbs = []
    imgs = page.locator("img")
    for i in range(min(imgs.count(), 90)):
        el = imgs.nth(i)
        try:
            box = el.bounding_box()
        except Exception:  # noqa: BLE001
            continue
        if box and box["width"] >= 110 and box["height"] >= 110 and box["y"] > 150:
            thumbs.append(el)
    return thumbs


def _wait_grid_ready(page, timeout_s: int = 40) -> list:
    """一覧に商品サムネが出るまで待つ。空なら「さらに読み込む」を押す。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        thumbs = _thumbs_now(page)
        if len(thumbs) >= 3:
            return thumbs
        if not _click_load_more(page):
            try:
                page.mouse.wheel(0, 600)
            except Exception:  # noqa: BLE001
                pass
        page.wait_for_timeout(1800)
    return _thumbs_now(page)


def _open_first_post(page, my_room: str, tries: int = 3) -> dict | None:
    """一覧の先頭の投稿詳細を開いて情報を返す。数回リトライ。"""
    for attempt in range(tries):
        _safe_goto(page, my_room)
        page.wait_for_timeout(2500)
        thumbs = _wait_grid_ready(page)
        if not thumbs:
            print(f"   （一覧の描画待ちリトライ {attempt + 2}/{tries}）")
            continue
        for el in thumbs[:8]:
            try:
                el.scroll_into_view_if_needed(timeout=3000)
                el.click(timeout=4000)
                page.wait_for_timeout(3200)
            except Exception:  # noqa: BLE001
                continue
            if not _pid(page.url):
                continue
            try:
                page.wait_for_selector(DEL_SEL, timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(900)
            try:
                info = page.evaluate(DETAIL_JS)
            except Exception:  # noqa: BLE001
                break
            info["url"] = page.url
            return info

    # 全リトライ失敗 → 状態を記録
    try:
        _safe_goto(page, my_room)
        page.wait_for_timeout(4000)
        body = ""
        try:
            body = page.locator("body").inner_text(timeout=4000)
        except Exception:  # noqa: BLE001
            pass
        dump = DATA_DIR / "prune_fail.txt"
        dump.write_text(
            f"URL: {page.url}\nimg数: {page.locator('img').count()}\n\n{body[:2000]}",
            encoding="utf-8",
        )
        try:
            page.screenshot(path=str(DATA_DIR / "prune_fail.png"), full_page=False)
        except Exception:  # noqa: BLE001
            pass
        print(f"   一覧を開けませんでした。状態を {dump} に記録しました。")
    except Exception:  # noqa: BLE001
        pass
    return None


def _delete_current(page, rec, pruned_log) -> bool:
    try:
        btn = page.locator(DEL_SEL).first
        btn.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(400)
        try:
            btn.click(timeout=5000)
        except Exception:  # noqa: BLE001
            # 見えない/被っている場合は JS で直接クリック
            btn.evaluate("el => el.click()")
        page.wait_for_timeout(4500)  # confirm 自動承認 → 削除
        rec["deleted_at"] = datetime.now().isoformat(timespec="seconds")
        pruned_log.append(rec)
        _save(PRUNE_LOG, pruned_log)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"    削除失敗: {exc}")
        return False


def _sleep_between(pcfg) -> None:
    lo, hi = pcfg.get("delete_interval_seconds", [3, 7])
    time.sleep(random.uniform(float(lo), float(hi)))


def _prune_oldest(page, cfg, pcfg, commit: bool) -> None:
    my_room = cfg["my_room_url"]
    max_delete = int(pcfg.get("max_delete_per_run", 12))
    only_before = (pcfg.get("only_before") or "").strip() or None

    pruned_log = _load(PRUNE_LOG, [])
    done = 0
    stopped = ""
    preview: list[dict] = []
    guard_hits = 0

    for _ in range(max_delete + 40):
        if done >= max_delete:
            break
        info = _open_first_post(page, my_room)
        if not info:
            stopped = "投稿を開けませんでした"
            break
        if not info.get("hasDelete"):
            stopped = "削除ボタンが無い投稿（自分の投稿でない？）"
            break

        posted = info.get("postedYmd")
        rec = {"url": info["url"], "name": info.get("name", "")[:100],
               "posted": posted, "likes": info.get("likes"),
               "comments": info.get("comments")}

        if only_before and posted and posted >= only_before:
            guard_hits += 1
            print(f"  スキップ（{posted} は {only_before} 以降）: {rec['name'][:40]}")
            # 先頭がガード対象＝それ以降は全部新しい → 終了
            stopped = f"先頭の投稿が {only_before} 以降（{posted}）。これ以上古い投稿はありません"
            break

        print(f"  {'[プレビュー] ' if not commit else ''}削除対象: {posted} {rec['name'][:44]}")
        preview.append(rec)
        if commit:
            if _delete_current(page, rec, pruned_log):
                done += 1
                print(f"    → 削除（{done}/{max_delete}）")
                _sleep_between(pcfg)
        else:
            # プレビューは先頭しか見られないのでここで打ち切り
            stopped = "プレビューは先頭1件のみ表示（本番なら順に削除）"
            break

    _save(PREVIEW_FILE, {"mode": "oldest", "would_delete_or_deleted": preview})
    print("\n" + "=" * 60)
    if commit:
        print(f"削除完了: {done} 件" + (f" / {stopped}" if stopped else ""))
    else:
        print("[プレビュー] oldest モードは本番実行で先頭から順に削除します。")
        if preview:
            print(f"  次に削除される投稿: {preview[0]['posted']} {preview[0]['name'][:50]}")
        if stopped:
            print(f"  {stopped}")


def _prune_soldout(page, cfg, pcfg, commit: bool) -> None:
    my_room = cfg["my_room_url"]
    max_delete = int(pcfg.get("max_delete_per_run", 12))
    prefer_zero = pcfg.get("prefer_zero_engagement", True)
    only_before = (pcfg.get("only_before") or "").strip() or None
    pruned_log = _load(PRUNE_LOG, [])

    info = _open_first_post(page, my_room)
    if not info:
        print("投稿を開けませんでした。")
        return

    hits, engaged = [], []
    deleted = scanned = stuck = 0
    last = None
    for _ in range(max_delete * 25 + 50):
        if commit and deleted >= max_delete:
            break
        cur = info if scanned == 0 else None
        if cur is None:
            try:
                page.wait_for_selector(DEL_SEL, timeout=6000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(700)
            try:
                cur = page.evaluate(DETAIL_JS)
                cur["url"] = page.url
            except Exception:  # noqa: BLE001
                cur = {}
        scanned += 1

        if cur.get("hasDelete") and cur.get("soldOut"):
            posted = cur.get("postedYmd")
            if not (only_before and posted and posted >= only_before):
                zero = (cur.get("likes") or 0) == 0 and (cur.get("comments") or 0) == 0
                rec = {"url": cur["url"], "name": cur.get("name", "")[:100],
                       "posted": posted, "likes": cur.get("likes"),
                       "comments": cur.get("comments"), "zero_engagement": zero}
                print(f"  売切れ({'反応なし' if zero else '反応あり'}): {rec['name'][:42]} {posted}")
                (hits if (zero or not prefer_zero) else engaged).append(rec)
                if commit and (zero or not prefer_zero):
                    if _delete_current(page, rec, pruned_log):
                        deleted += 1
                        print(f"    → 削除（{deleted}/{max_delete}）")
                        time.sleep(1.5)
                        info = _open_first_post(page, my_room)
                        scanned = 0
                        continue

        # 次の投稿へ
        if page.url == last:
            stuck += 1
            if stuck >= 3:
                break
        else:
            stuck = 0
        last = page.url
        try:
            nxt = page.locator(NEXT_SEL).first
            if not nxt.count():
                break
            nxt.click(timeout=4000)
            page.wait_for_timeout(1700)
        except Exception:  # noqa: BLE001
            break

    if commit and deleted < max_delete and engaged:
        print("反応ありの売切れも削除して枠を埋めます...")
        for rec in engaged:
            if deleted >= max_delete:
                break
            _safe_goto(page, rec["url"])
            try:
                page.wait_for_selector(DEL_SEL, timeout=8000)
            except Exception:  # noqa: BLE001
                continue
            page.wait_for_timeout(700)
            if _delete_current(page, rec, pruned_log):
                deleted += 1
                print(f"    → 削除（{deleted}/{max_delete}）: {rec['name'][:40]}")

    _save(PREVIEW_FILE, {"mode": "soldout", "soldout_zero": hits, "soldout_engaged": engaged})
    print("\n" + "=" * 60)
    if commit:
        print(f"削除完了: {deleted} 件（{scanned} 件チェック）")
    else:
        print(f"[プレビュー] 売切れ・反応なし {len(hits)} 件 / 売切れ・反応あり {len(engaged)} 件"
              f"（{scanned} 件チェック）")
        print(f"詳細: {PREVIEW_FILE}")


def prune(cfg: dict, commit: bool = False) -> None:
    pcfg = cfg.get("prune", {})
    if not pcfg.get("enabled", False):
        print("prune は config.yaml で無効になっています。")
        return
    if not cfg.get("my_room_url"):
        print("config.yaml の my_room_url が未設定です。")
        return

    mode = (pcfg.get("mode") or "oldest").strip()
    pw, ctx, _b = _launch()
    accept = {"on": commit}

    def on_dialog(d):
        try:
            d.accept() if accept["on"] else d.dismiss()
        except Exception:  # noqa: BLE001
            pass

    try:
        page = ctx.new_page()
        page.on("dialog", on_dialog)
        print(f"モード: {mode} / {'本番削除' if commit else 'プレビュー'} / "
              f"最大 {pcfg.get('max_delete_per_run', 12)} 件 / "
              f"ガード: {pcfg.get('only_before') or 'なし'}")
        if mode == "soldout":
            _prune_soldout(page, cfg, pcfg, commit)
        else:
            _prune_oldest(page, cfg, pcfg, commit)
    finally:
        pw.stop()
