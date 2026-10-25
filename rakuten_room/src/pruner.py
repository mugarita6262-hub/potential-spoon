"""上限対策: 自分のROOMの古い / 売切れ投稿を削除して空きを作る。

mode="oldest"  : 一覧の先頭（古い投稿）から順に削除
mode="soldout" : 売切れ投稿だけ削除（反応なしを優先）

only_before ガード: その日付より後の投稿は削除しない。
commit=False（プレビュー）では削除しない。
削除は confirm ダイアログ（この商品を削除してよろしいですか？）を自動承認。
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import DATA_DIR
from .poster import _launch, _safe_goto

PRUNE_LOG = DATA_DIR / "pruned.json"
PREVIEW_FILE = DATA_DIR / "prune_preview.json"

DETAIL_RE = re.compile(r"/room_[0-9a-z]+/(\d{6,})")
NEXT_SEL = 'button[aria-label="swipe-right"]'
DEL_SEL = 'button[aria-label="削除"]'
# 「掲載終了商品を含む」ON のURL。この一覧は 60件ほど一気に読み込まれて安定
LIST_QUERY = "?unavailable_item=1"

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
    # 一時ファイルに書いてから置き換える（書いている途中で止められてもファイルが壊れない。2026-10-26）
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _load_prune_log() -> list:
    """削除の記録。読めないときに [] で始めると、次の保存で過去の記録を消し、上限も数え直してしまうので止める。"""
    if not PRUNE_LOG.exists():
        return []
    try:
        return json.loads(PRUNE_LOG.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"{PRUNE_LOG.name} が読めないので削除を止めます: {exc}") from exc


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _limit_reached(pruned_log: list, pcfg: dict) -> str:
    """1日の削除の上限に達していたら理由を返す。1時間の上限は _wait_hour_limit で待つ（打ち切ると件数が減る）。"""
    today = datetime.now().date().isoformat()
    n_today = sum(1 for r in pruned_log[-3000:] if (r.get("deleted_at") or "")[:10] == today)
    per_day = int(pcfg.get("delete_per_day", 600))
    if n_today >= per_day:
        return f"今日の削除が上限 {per_day} 件に達した"
    return ""


def _wait_hour_limit(pruned_log: list, pcfg: dict, started: float) -> bool:
    """直近1時間の削除が上限なら、いちばん古い1件が1時間を過ぎるまで待つ（2026-10-26: 上限で打ち切ると
    2回目の回が20件ほどで止まり、1日の件数が減っていた）。1回の長さの上限（max_run_minutes）を超えるなら False。"""
    per_hour = int(pcfg.get("delete_per_hour", 150))
    max_run = float(pcfg.get("max_run_minutes", 75)) * 60
    while True:
        now = datetime.now()
        hour_ago = (now - timedelta(hours=1)).isoformat(timespec="seconds")
        recent = sorted(r.get("deleted_at") or "" for r in pruned_log[-2000:] if (r.get("deleted_at") or "") >= hour_ago)
        if len(recent) < per_hour:
            return True
        wait = (datetime.fromisoformat(recent[len(recent) - per_hour]) + timedelta(hours=1) - now).total_seconds()
        wait = max(30.0, wait) + random.uniform(5, 40)
        if time.time() - started + wait > max_run:
            print(f"  直近1時間の削除が上限 {per_hour} 件で、待つと回が長くなりすぎるので、この回はここまでにします")
            return False
        print(f"  直近1時間の削除が上限 {per_hour} 件なので、{int(wait / 60)}分ほど待ってから続けます")
        time.sleep(wait)


def _pid(s: str) -> str:
    m = DETAIL_RE.search(s or "")
    return m.group(1) if m else ""


LOAD_MORE_LABELS = ["さらに読み込む", "もっと読み込む", "もっと見る", "続きを見る"]


def _find_load_more(page):
    """『さらに読み込む』ボタンを返す（無ければ None）。"""
    selectors = []
    for lb in LOAD_MORE_LABELS:
        selectors += [f'button:has-text("{lb}")', f'a:has-text("{lb}")',
                      f'[role="button"]:has-text("{lb}")', f'text="{lb}"']
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                return loc
        except Exception:  # noqa: BLE001
            continue
    return None


CARD_SEL = "a.link-image--2kguM, a[class*='link-image']"


def _cards_now(page) -> list:
    """クリックすると投稿詳細に飛ぶカード要素（href なし・JS onclick）。"""
    out = []
    try:
        loc = page.locator(CARD_SEL)
        n = loc.count()
    except Exception:  # noqa: BLE001
        return out
    for i in range(min(n, 60)):
        el = loc.nth(i)
        try:
            if el.is_visible():
                out.append(el)
        except Exception:  # noqa: BLE001
            continue
    return out


def _thumbs_now(page) -> list:
    return _cards_now(page)


def _wait_grid_ready(page, want: int = 5, timeout_s: int = 50) -> list:
    """一覧に投稿カードが want 件出るまで待つ。
    『さらに読み込む』があれば押し、無ければスクロールで誘発。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        cards = _cards_now(page)
        if len(cards) >= want:
            return cards
        btn = _find_load_more(page)
        if btn is not None:
            try:
                btn.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(250)
                btn.click(timeout=4000)
            except Exception:  # noqa: BLE001
                try:
                    btn.evaluate("el => el.click()")
                except Exception:  # noqa: BLE001
                    pass
            page.wait_for_timeout(2400)
        else:
            # ボタンが無い＝まだ描画中 or 無限スクロール。上下に動かして誘発
            for dy in (2500, 2500, -6000):
                try:
                    page.mouse.wheel(0, dy)
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(1100)
    return _cards_now(page)


def _list_url(my_room: str) -> str:
    base = my_room.split("?")[0]
    return base + LIST_QUERY


def _open_first_post(page, my_room: str, tries: int = 3) -> dict | None:
    """一覧の先頭の投稿詳細を開いて情報を返す。数回リトライ。"""
    for attempt in range(tries):
        _safe_goto(page, _list_url(my_room))
        page.wait_for_timeout(3500)
        thumbs = _wait_grid_ready(page)
        if len(thumbs) < 2:
            print(f"   （一覧の描画待ちリトライ {attempt + 2}/{tries}）")
            continue
        for el in thumbs[:10]:
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


def _prune_oldest(page, cfg, pcfg, commit: bool) -> None:
    from .human import Pacer

    my_room = cfg["my_room_url"]
    max_delete = int(pcfg.get("max_delete_per_run", 12))
    only_before = (pcfg.get("only_before") or "").strip() or None
    lo, hi = pcfg.get("delete_interval_seconds", [4, 9])
    pacer = Pacer(base=(float(lo), float(hi)))

    pruned_log = _load(PRUNE_LOG, [])
    done = 0
    stopped = ""
    preview: list[dict] = []
    fail_streak = 0

    while done < max_delete and not stopped:
        info = _open_first_post(page, my_room)
        if not info:
            fail_streak += 1
            if fail_streak >= 3:
                stopped = "一覧を開けませんでした（3回連続）。時間をあけて再実行してください"
                break
            time.sleep(20)  # 一時制限の可能性 → 少し待って再挑戦
            continue
        fail_streak = 0

        if not info.get("hasDelete"):
            stopped = "削除ボタンが無い投稿"
            break
        posted = info.get("postedYmd")
        rec = {"url": info["url"], "name": info.get("name", "")[:100],
               "posted": posted, "likes": info.get("likes"), "comments": info.get("comments")}
        if only_before and posted and posted >= only_before:
            stopped = f"先頭の投稿が {only_before} 以降（{posted}）。これ以上古い投稿はありません"
            break
        # 投稿日が読めない投稿は消さない。新しい投稿は「〇時間前」表示で日付が取れず、
        # 以前はガードをすり抜けて削除されていた（2026-09-08〜10-13に新しい投稿664件を誤削除）
        if only_before and not posted:
            stopped = "投稿日が読めない投稿（新しい投稿の可能性）。安全のため止めます"
            break
        print(f"  {'[プレビュー] ' if not commit else ''}削除対象: {posted} {rec['name'][:44]}")
        preview.append(rec)
        if not commit:
            stopped = "プレビューは先頭1件のみ表示（本番なら順に削除）"
            break
        if _delete_current(page, rec, pruned_log):
            done += 1
            print(f"    → 削除（{done}/{max_delete}）")
            if done < max_delete:
                pacer.wait(on_rest=lambda s: print(f"    （ひと休み {int(s)}秒）"))

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
            if posted and not (only_before and posted >= only_before):  # 日付が読めない（新しい）投稿は消さない
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


API = "https://room.rakuten.co.jp/api"


def _api_post(page, url: str, body: str) -> tuple[int, str]:
    res = page.evaluate(
        """([u,b])=>fetch(u,{method:'POST',credentials:'include',
            headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
            body:b}).then(r=>r.text().then(t=>({s:r.status,t})))""", [url, body])
    return res.get("s") or 0, res.get("t") or ""


def _last_offset(page, uid: str, tok: str, hint: int = 0) -> int:
    """投稿一覧の最後（いちばん古い投稿）が何件目かを二分探索で探す。"""
    from .engage import _api_get

    def has(off):
        return bool(_api_get(page, f"{API}/{uid}/collects?api_version=1&limit=1&offset={off}&csrf_tkn={tok}").get("data"))

    lo, hi = 0, max(hint * 2, 32768)
    while not has(lo):
        return -1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if has(mid):
            lo = mid
        else:
            hi = mid
        time.sleep(0.4)
    return lo


def _prune_oldest_api(page, cfg, pcfg, commit: bool) -> None:
    """ROOMの内部APIで、いちばん古い投稿から順に削除する（2026-10-13 作り直し）。

    以前の方式は「掲載終了を含む」一覧の先頭（＝新しい投稿）を開いており、新しい投稿は日付が
    「〇時間前」表示で読めずにガードをすり抜け、新しい投稿を大量に消していた。
    API方式では一覧の末尾（オフセット最大）から、作成日時が only_before より前の投稿だけを消す。
    """
    from .engage import _api_get, _api_session
    from .human import Pacer
    slug = cfg["my_room_url"].rstrip("/").split("/")[-2]
    only_before = (pcfg.get("only_before") or "").strip()
    if not only_before:
        print("only_before が未設定のため、安全のため削除しません。")
        return
    max_delete = int(pcfg.get("max_delete_per_run", 12))
    lo, hi = pcfg.get("delete_interval_seconds", [4, 9])
    pacer = Pacer(base=(float(lo), float(hi)))
    uid, tok = _api_session(page, slug)
    state = _load(DATA_DIR / "prune_state.json", {})
    last = _last_offset(page, uid, tok, int(state.get("last_offset", 0)))
    if last < 0:
        print("投稿一覧が取れませんでした。")
        return
    state["last_offset"] = last
    _save(DATA_DIR / "prune_state.json", state)
    start = max(0, last - 99)
    data = _api_get(page, f"{API}/{uid}/collects?api_version=1&limit=100&offset={start}&csrf_tkn={tok}").get("data") or []
    olds = [c for c in data if (c.get("created_at") or "9999") < only_before]
    # 反応のない投稿を先に、その中で古い順
    olds.sort(key=lambda c: ((c.get("likes") or 0) + (c.get("comments") or 0) > 0, c.get("created_at") or ""))
    print(f"  一覧の末尾 {len(data)} 件のうち、{only_before} より前の投稿 {len(olds)} 件（全体 約{last + 1}件）")
    pruned_log = _load_prune_log()
    done = 0
    refreshed = False
    started = time.time()
    for c in olds[:max_delete]:
        rec = {"url": f"https://room.rakuten.co.jp/{slug}/{c['id']}", "name": (c.get("content") or c.get("name") or "")[:100],
               "posted": (c.get("created_at") or "")[:10], "likes": c.get("likes"), "comments": c.get("comments")}
        if not commit:
            print(f"  [プレビュー] 削除対象: {rec['posted']} {rec['name'][:44]}")
            continue
        why = _limit_reached(pruned_log, pcfg)
        if why:
            print(f"  {why}ので、この回はここまでにします")
            break
        if not _wait_hour_limit(pruned_log, pcfg, started):
            break
        # 最終確認：ガードより新しい・日付不明・日付の形が違う投稿は絶対に消さない（2026-10-13の誤削除の再発防止）
        if not _DATE_RE.match(rec["posted"]) or rec["posted"] >= only_before:
            from .notify import notify
            msg = f"ROOM削除を停止: ガード({only_before})より新しい投稿を消そうとしました（{rec['posted']} {rec['name'][:30]}）"
            print("  " + msg)
            notify(msg, title="ROOM prune STOPPED")
            break
        s, text = _api_post(page, f"{API}/{c['id']}?csrf_tkn={tok}", "_method=delete")
        if not (s == 200 and '"success"' in text) and not refreshed:
            # 長い回の途中でログイン情報（トークン）が切れることがあるので、1回だけ取り直してやり直す
            refreshed = True
            try:
                uid, tok = _api_session(page, slug)
                s, text = _api_post(page, f"{API}/{c['id']}?csrf_tkn={tok}", "_method=delete")
            except Exception:  # noqa: BLE001
                pass
        if s == 200 and '"success"' in text:
            done += 1
            rec["deleted_at"] = datetime.now().isoformat(timespec="seconds")
            pruned_log.append(rec)
            # 1件ごとに記録する（回の最後にまとめて書くと、途中で止められた回の削除が記録に残らない。2026-10-24）
            _save(PRUNE_LOG, pruned_log)
            print(f"  削除: {rec['posted']} {rec['name'][:44]}")
        else:
            print(f"  削除できませんでした（{s} {text[:120]}）。この回は止めます")
            break
        pacer.wait()
    if commit:
        _save(PRUNE_LOG, pruned_log)
    print(f"削除完了: {done} 件")


def _is_dead(c: dict) -> bool:
    """販売が終わった商品の投稿か（売り切れ・商品削除・在庫なし）。ROOMの投稿APIの item にある値で判定する。"""
    it = c.get("item") or {}
    return bool(it.get("flg_soldout") or it.get("flg_deleted") or str(it.get("availability", "1")) != "1")


def _prune_dead_api(page, cfg, pcfg, commit: bool) -> None:
    """販売が終わった商品の投稿だけを消す（2026-10-18 追加）。

    それまでの oldest は「2025年より前で反応の少ない順」に消していたが、2022年の投稿20件を見ると販売中が14件で、
    売れる可能性のある投稿を消し、販売終了の投稿を残していた。こちらは販売終了だけを、古い方から探して消す。
    対象は only_before（2025-01-01）より前の投稿だけ。このツールで投稿したもの（2025年以降）は、販売終了でも絶対に消さない
    （ユーザー指示: 必死に増やした投稿を消すのは絶対にだめ。10/13 の誤削除の再発防止も兼ねる）。
    販売終了で1回の枠が余ったら、残りは oldest（only_before より前を古い順）で消す。
    """
    from .engage import _api_get, _api_session
    from .human import Pacer
    slug = cfg["my_room_url"].rstrip("/").split("/")[-2]
    cutoff = (pcfg.get("only_before") or "").strip()
    if not cutoff:
        print("only_before が未設定のため、安全のため削除しません。")
        return
    max_delete = int(pcfg.get("max_delete_per_run", 12))
    lo, hi = pcfg.get("delete_interval_seconds", [4, 9])
    pacer = Pacer(base=(float(lo), float(hi)))
    uid, tok = _api_session(page, slug)
    state = _load(DATA_DIR / "prune_state.json", {})
    last = _last_offset(page, uid, tok, int(state.get("last_offset", 0)))
    if last < 0:
        print("投稿一覧が取れませんでした。")
        return
    state["last_offset"] = last
    # 前回どこまで見たか（古い方から新しい方へ進む）。末尾を超えていたら、末尾から見直す
    cur = int(state.get("dead_cursor", last))
    if cur > last or cur < 0:
        cur = last
    found, scanned = [], 0
    while len(found) < max_delete and scanned < int(pcfg.get("scan_per_run", 1500)):
        start = max(0, cur - 99)
        data = _api_get(page, f"{API}/{uid}/collects?api_version=1&limit=100&offset={start}&csrf_tkn={tok}").get("data") or []
        if not data:
            break
        scanned += len(data)
        found += [c for c in data if (c.get("created_at") or "9999") < cutoff and _is_dead(c)]
        # ここから先（新しい側）が only_before 以降になったら、末尾に戻って次回また古い方から見る
        if start == 0 or min((c.get("created_at") or "9999") for c in data) >= cutoff:
            cur = last
            break
        cur = start - 1
    state["dead_cursor"] = cur
    _save(DATA_DIR / "prune_state.json", state)
    print(f"  販売終了の投稿を探索: {scanned} 件を見て {len(found)} 件（全体 約{last + 1}件・{cutoff} より前のみ）")
    pruned_log = _load_prune_log()
    done = 0
    refreshed = False
    started = time.time()
    for c in found[:max_delete]:
        it = c.get("item") or {}
        rec = {"url": f"https://room.rakuten.co.jp/{slug}/{c['id']}", "name": (c.get("content") or it.get("name") or "")[:100],
               "posted": (c.get("created_at") or "")[:10], "likes": c.get("likes"), "comments": c.get("comments"),
               "reason": "soldout" if it.get("flg_soldout") else "deleted" if it.get("flg_deleted") else f"availability={it.get('availability')}"}
        if not commit:
            print(f"  [プレビュー] 削除対象: {rec['posted']} {rec['reason']} {it.get('name', '')[:40]}")
            continue
        why = _limit_reached(pruned_log, pcfg)
        if why:
            print(f"  {why}ので、この回はここまでにします")
            break
        if not _wait_hour_limit(pruned_log, pcfg, started):
            break
        # 最終確認：新しい投稿・日付不明・日付の形が違う・販売中は絶対に消さない
        if not _DATE_RE.match(rec["posted"]) or rec["posted"] >= cutoff or not _is_dead(c):
            from .notify import notify
            msg = f"ROOM削除を停止: 消してはいけない投稿を消そうとしました（{rec['posted']} {rec['reason']} {rec['name'][:30]}）"
            print("  " + msg)
            notify(msg, title="ROOM prune STOPPED")
            break
        s, text = _api_post(page, f"{API}/{c['id']}?csrf_tkn={tok}", "_method=delete")
        if not (s == 200 and '"success"' in text) and not refreshed:
            # 長い回の途中でログイン情報（トークン）が切れることがあるので、1回だけ取り直してやり直す
            refreshed = True
            try:
                uid, tok = _api_session(page, slug)
                s, text = _api_post(page, f"{API}/{c['id']}?csrf_tkn={tok}", "_method=delete")
            except Exception:  # noqa: BLE001
                pass
        if s == 200 and '"success"' in text:
            done += 1
            rec["deleted_at"] = datetime.now().isoformat(timespec="seconds")
            pruned_log.append(rec)
            # 1件ごとに記録する（回の最後にまとめて書くと、途中で止められた回の削除が記録に残らない。2026-10-24）
            _save(PRUNE_LOG, pruned_log)
            print(f"  削除: {rec['posted']} {rec['reason']} {it.get('name', '')[:40]}")
        else:
            print(f"  削除できませんでした（{s} {text[:120]}）。この回は止めます")
            break
        pacer.wait()
    if commit:
        _save(PRUNE_LOG, pruned_log)
    print(f"削除完了: {done} 件（販売終了）")
    # 販売終了で枠が余ったら、古い投稿（only_before より前。2022年ごろの意図の分からない投稿）を古い順に消す
    # （2026-10-18 ユーザー指示: 販売終了 → 古い商品 の順で消す）
    if done < max_delete:
        print(f"  残り {max_delete - done} 件は、{pcfg.get('only_before')} より前の古い投稿を古い順に消します")
        _prune_oldest_api(page, cfg, {**pcfg, "max_delete_per_run": max_delete - done}, commit)


def prune(cfg: dict, commit: bool = False, max_delete: int | None = None) -> None:
    pcfg = dict(cfg.get("prune", {}))
    if not pcfg.get("enabled", False):
        print("prune は config.yaml で無効になっています。")
        return
    if not cfg.get("my_room_url"):
        print("config.yaml の my_room_url が未設定です。")
        return
    if max_delete is not None:
        pcfg["max_delete_per_run"] = max_delete
        if max_delete <= 0:
            print("この回の削除は0件です（今日の分は済んでいます）。")
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
        elif mode == "dead":
            _prune_dead_api(page, cfg, pcfg, commit)
        else:
            _prune_oldest_api(page, cfg, pcfg, commit)
    finally:
        try:
            page.close()  # 自分のタブは閉じる（溜まると Chrome が重くなる）
        except Exception:  # noqa: BLE001
            pass
        pw.stop()
