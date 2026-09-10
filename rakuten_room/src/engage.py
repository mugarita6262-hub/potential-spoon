"""いいね回り / フォロー回り / フォロー整理（慎重な半自動）。

- 1日・1時間の上限を保守的に設定（楽天ROOMの公称上限よりかなり低め）
- Pacer で人間らしいランダム間隔・ときどき休憩
- 実績は data/engage_log.json に記録（当日カウント用）
- いつでも Ctrl+C / GUI の中断で止められる
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import DATA_DIR
from .human import Pacer, jitter, maybe_pause_long
from .poster import _launch, _safe_goto

LOG = DATA_DIR / "engage_log.json"
FOLLOW_LOG = DATA_DIR / "follow_log.json"   # {slug: {"at": iso, "back": bool|null}}

NEW_FEED = "https://room.rakuten.co.jp/search/item?sort=new"
HOME_FEED = "https://room.rakuten.co.jp/"
NOTIF = "https://room.rakuten.co.jp/{slug}/notifications"

LIKE_SEL = 'a.icon-like.right'          # ng-click="like(item)"
# デフォルト上限（慎重）: 公称 いいね800/日・フォロー1000/日,100/時 に対しかなり低く
DEFAULT_CAPS = {
    "like_per_day": 200, "like_per_hour": 35,
    "follow_per_day": 80, "follow_per_hour": 15,
    "unfollow_per_day": 60,
}


def _load(p: Path, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def _save(p: Path, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _today_log() -> dict:
    log = _load(LOG, {})
    t = date.today().isoformat()
    return log.setdefault(t, {"like": 0, "follow": 0, "unfollow": 0, "events": []})


def _bump(kind: str, n: int = 1) -> None:
    log = _load(LOG, {})
    t = date.today().isoformat()
    d = log.setdefault(t, {"like": 0, "follow": 0, "unfollow": 0, "events": []})
    d[kind] = d.get(kind, 0) + n
    d["events"].append({"kind": kind, "at": datetime.now().isoformat(timespec="seconds")})
    d["events"] = d["events"][-400:]
    _save(LOG, log)


def _count_last_hour(kind: str) -> int:
    d = _today_log()
    cutoff = datetime.now() - timedelta(hours=1)
    n = 0
    for e in d.get("events", []):
        if e.get("kind") != kind:
            continue
        try:
            if datetime.fromisoformat(e["at"]) >= cutoff:
                n += 1
        except (KeyError, ValueError):
            pass
    return n


def _caps(cfg: dict) -> dict:
    c = dict(DEFAULT_CAPS)
    c.update(cfg.get("engage", {}).get("caps", {}) or {})
    return c


def _remaining(cfg: dict, kind: str) -> tuple[int, int]:
    """(今日あと何回できるか, 今時間あと何回できるか)"""
    caps = _caps(cfg)
    day_done = _today_log().get(kind, 0)
    day_left = max(0, int(caps.get(f"{kind}_per_day", 999)) - day_done)
    hour_cap = int(caps.get(f"{kind}_per_hour", 999))
    hour_left = max(0, hour_cap - _count_last_hour(kind))
    return day_left, hour_left


# ---------------- いいね回り ----------------
def like_round(cfg: dict, target: int, feed: str = "new") -> None:
    day_left, hour_left = _remaining(cfg, "like")
    can = min(target, day_left, hour_left)
    if can <= 0:
        print(f"いいねの上限に達しています（今日 {_today_log()['like']} 件 / "
              f"直近1時間 {_count_last_hour('like')} 件）。時間をおいてください。")
        return
    if can < target:
        print(f"上限の都合でこの回は {can} 件までにします（今日/1時間の残り）。")

    url = NEW_FEED if feed == "new" else HOME_FEED
    pacer = Pacer(base=tuple(cfg.get("engage", {}).get("like_interval", [5, 13])))

    pw, ctx, _b = _launch()
    try:
        page = ctx.new_page()
        _safe_goto(page, url)
        page.wait_for_timeout(5000)
        done = 0
        misses = 0
        while done < can and misses < 6:
            btns = _fresh_like_buttons(page)
            if not btns:
                # スクロールで読み込み
                for _ in range(3):
                    page.mouse.wheel(0, 2200)
                    page.wait_for_timeout(1200)
                misses += 1
                continue
            misses = 0
            for b in btns:
                if done >= can:
                    break
                try:
                    b.scroll_into_view_if_needed(timeout=3000)
                    jitter(0.8)
                    b.click(timeout=4000)
                    done += 1
                    _bump("like")
                    print(f"  ♡ いいね {done}/{can}")
                    pacer.wait(on_rest=lambda s: print(f"    （ひと休み {int(s)}秒）"))
                    maybe_pause_long(0.04, (15, 45))
                except Exception:  # noqa: BLE001
                    continue
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(1500)
        print(f"\nいいね回り完了: {done} 件（今日の累計 {_today_log()['like']} 件）")
    finally:
        pw.stop()


def _fresh_like_buttons(page) -> list:
    """まだ押していない（＝『いいね』表示の）ボタンを、画面内優先で返す。"""
    out = []
    loc = page.locator(LIKE_SEL)
    try:
        n = loc.count()
    except Exception:  # noqa: BLE001
        return out
    for i in range(min(n, 60)):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            txt = (el.inner_text() or "").strip()
            cls = (el.get_attribute("class") or "")
            if "いいね" in txt and "済" not in txt and "on" not in cls.split():
                out.append(el)
        except Exception:  # noqa: BLE001
            continue
    return out


# ---------------- フォロー回り（お知らせ経由＝アクティブ確定） ----------------
def follow_round(cfg: dict, target: int, slug: str) -> None:
    day_left, hour_left = _remaining(cfg, "follow")
    can = min(target, day_left, hour_left)
    if can <= 0:
        print(f"フォローの上限に達しています（今日 {_today_log()['follow']} 件）。時間をおいてください。")
        return

    pacer = Pacer(base=tuple(cfg.get("engage", {}).get("follow_interval", [8, 20])))
    flog = _load(FOLLOW_LOG, {})

    pw, ctx, _b = _launch()
    try:
        page = ctx.new_page()
        _safe_goto(page, NOTIF.format(slug=slug))
        page.wait_for_timeout(5000)
        # 「あなたへのお知らせ / アクティビティ」タブへ
        for lb in ["あなたへ", "アクティビティ", "いいね", "フォロー"]:
            try:
                t = page.get_by_text(lb, exact=False).first
                if t.count() and t.is_visible():
                    t.click(timeout=3000)
                    page.wait_for_timeout(2500)
                    break
            except Exception:  # noqa: BLE001
                pass

        done = 0
        misses = 0
        while done < can and misses < 6:
            targets = _unfollowed_in_notifications(page)
            if not targets:
                for _ in range(3):
                    page.mouse.wheel(0, 2200)
                    page.wait_for_timeout(1200)
                misses += 1
                continue
            misses = 0
            for btn, name in targets:
                if done >= can:
                    break
                try:
                    btn.scroll_into_view_if_needed(timeout=3000)
                    jitter(1.0)
                    btn.click(timeout=4000)
                    done += 1
                    _bump("follow")
                    flog[name] = {"at": datetime.now().isoformat(timespec="seconds"),
                                  "back": None}
                    _save(FOLLOW_LOG, flog)
                    print(f"  + フォロー {done}/{can}  {name}")
                    pacer.wait(on_rest=lambda s: print(f"    （ひと休み {int(s)}秒）"))
                except Exception:  # noqa: BLE001
                    continue
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(1500)
        print(f"\nフォロー回り完了: {done} 件（今日の累計 {_today_log()['follow']} 件）")
    finally:
        pw.stop()


def _unfollowed_in_notifications(page) -> list:
    """「○○さんがいいね/フォロー」の行で『未フォロー』の要素を返す。"""
    out = []
    rows = page.locator('li:has(span.follow)')
    try:
        n = rows.count()
    except Exception:  # noqa: BLE001
        return out
    for i in range(min(n, 40)):
        row = rows.nth(i)
        try:
            if not row.is_visible():
                continue
            fol = row.locator("span.follow").first
            label = (fol.inner_text() or "").strip()
            if label != "未フォロー":
                continue
            name = ""
            m = re.search(r"^(.+?)\s*さん", (row.inner_text() or "").strip())
            if m:
                name = m.group(1)[:40]
            out.append((fol, name or f"row{i}"))
        except Exception:  # noqa: BLE001
            continue
    return out


# ---------------- フォロー整理 ----------------
def unfollow_round(cfg: dict, slug: str) -> None:
    ec = cfg.get("engage", {})
    keep_days = int(ec.get("unfollow_after_days", 10))
    caps = _caps(cfg)
    can = max(0, int(caps.get("unfollow_per_day", 60)) - _today_log().get("unfollow", 0))
    if can <= 0:
        print("フォロー整理の上限に達しています。")
        return

    flog = _load(FOLLOW_LOG, {})
    cutoff = datetime.now() - timedelta(days=keep_days)
    stale = [name for name, v in flog.items()
             if v.get("back") is not True
             and _before(v.get("at"), cutoff)]
    if not stale:
        print(f"整理対象がありません（{keep_days}日以上前にフォローしてフォロバ無しの相手）。")
        return

    pacer = Pacer(base=(6.0, 16.0))
    pw, ctx, _b = _launch()
    try:
        page = ctx.new_page()
        _safe_goto(page, f"https://room.rakuten.co.jp/{slug}/follow")
        page.wait_for_timeout(5000)
        done = 0
        for name in stale:
            if done >= can:
                break
            # 名前で行を探して「フォロー中」を解除
            try:
                row = page.locator(f'li:has-text("{name}")').first
                if not row.count():
                    continue
                btn = row.locator('span.follow, button:has-text("フォロー")').first
                if not btn.count():
                    continue
                btn.scroll_into_view_if_needed(timeout=3000)
                jitter(1.0)
                btn.click(timeout=4000)
                page.wait_for_timeout(1200)
                done += 1
                _bump("unfollow")
                flog.pop(name, None)
                _save(FOLLOW_LOG, flog)
                print(f"  - 解除 {done}  {name}")
                pacer.wait()
            except Exception:  # noqa: BLE001
                continue
        print(f"\nフォロー整理完了: {done} 件")
    finally:
        pw.stop()


def _before(iso: str | None, cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(iso) < cutoff
    except (TypeError, ValueError):
        return False


def engage_status(cfg: dict) -> dict:
    d = _today_log()
    caps = _caps(cfg)
    return {
        "like": (d.get("like", 0), caps["like_per_day"]),
        "follow": (d.get("follow", 0), caps["follow_per_day"]),
        "unfollow": (d.get("unfollow", 0), caps["unfollow_per_day"]),
        "like_hour": (_count_last_hour("like"), caps["like_per_hour"]),
    }
