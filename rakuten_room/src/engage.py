"""いいね回り / フォロー回り / フォロー整理（慎重な半自動）。

- 1日・1時間の上限を保守的に設定（楽天ROOMの公称上限よりかなり低め）
- Pacer で人間らしいランダム間隔・ときどき休憩
- 実績は data/engage_log.json に記録（当日カウント用）
- いつでも Ctrl+C / GUI の中断で止められる
"""
from __future__ import annotations

import json
import random
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import DATA_DIR
from .human import Pacer, jitter, maybe_pause_long
from .poster import _launch, _safe_goto

LOG = DATA_DIR / "engage_log.json"
ROOM_LISTS = DATA_DIR / "room_lists.json"  # その日のフォロワー/フォロー一覧（1日1回取得）
ROOM_STATS_DETAIL = DATA_DIR / "room_stats_detail.json"  # 直近のフォロワー/フォロー/相互の数（API集計）
ROOM_STATS = DATA_DIR / "room_stats.json"  # {date: {"followers": n, "following": n}} 施策の効果を見るため
FOLLOW_LOG = DATA_DIR / "follow_log.json"   # {slug: {"at": iso, "back": bool|null}}

NEW_FEED = "https://room.rakuten.co.jp/search/item?sort=new"
HOME_FEED = "https://room.rakuten.co.jp/"
NOTIF = "https://room.rakuten.co.jp/{slug}/notifications"

LIKE_SEL = 'a.icon-like.right'          # ng-click="like(item)"
# デフォルト上限: 公称 いいね800/日・フォロー1000/日,100/時 の少し手前（2026-10-11 ユーザー判断で
# 以前使っていた ROOM REPEAT 極 と同じく制限近くまで動かす方針に変更。config の engage.caps で上書き可）
DEFAULT_CAPS = {
    "like_per_day": 700, "like_per_hour": 90,
    "follow_per_day": 800, "follow_per_hour": 90,
    "unfollow_per_day": 800,
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
        while done < can and misses < 8:
            b = _next_like_button(page)
            if b is None:
                for _ in range(3):
                    page.mouse.wheel(0, 2400)
                    page.wait_for_timeout(1300)
                misses += 1
                continue
            misses = 0
            try:
                b.scroll_into_view_if_needed(timeout=3000)
                # 押したボタンに印をつけて二度押ししない
                b.evaluate("el => el.setAttribute('data-tool-done','1')")
                jitter(0.8)
                b.click(timeout=4000)
                page.wait_for_timeout(800)
                done += 1
                _bump("like")
                print(f"  ♡ いいね {done}/{can}")
                if done < can:
                    pacer.wait(on_rest=lambda s: print(f"    （ひと休み {int(s)}秒）"))
                    maybe_pause_long(0.04, (15, 45))
            except Exception:  # noqa: BLE001
                continue
        print(f"\nいいね回り完了: {done} 件（今日の累計 {_today_log()['like']} 件）")
    finally:
        try:
            page.close()  # 自分のタブは閉じる（溜まると Chrome が重くなる）
        except Exception:  # noqa: BLE001
            pass
        pw.stop()


def _next_like_button(page):
    """まだ押していない いいねボタンを1つ返す。無ければ None。
    印(data-tool-done)・『済』表示・on クラスは除外。"""
    loc = page.locator(f"{LIKE_SEL}:not([data-tool-done])")
    try:
        n = loc.count()
    except Exception:  # noqa: BLE001
        return None
    for i in range(min(n, 60)):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            txt = (el.inner_text() or "").strip()
            cls = (el.get_attribute("class") or "").split()
            if "いいね" in txt and "済" not in txt and "on" not in cls and "liked" not in cls:
                return el
        except Exception:  # noqa: BLE001
            continue
    return None


# ---------------- フォロー回り（お知らせ経由＝アクティブ確定） ----------------
ACTIVITY_ROW = 'li[ng-repeat*="activityNotification"]'
FOLLOW_BTN_SEL = ('button[aria-label="フォローする"], button[aria-label="フォロー"], '
                  'a:has-text("フォローする"), button:has-text("フォローする")')


def follow_round(cfg: dict, target: int, slug: str) -> None:
    day_left, hour_left = _remaining(cfg, "follow")
    can = min(target, day_left, hour_left)
    if can <= 0:
        print(f"フォローの上限に達しています（今日 {_today_log()['follow']} 件）。時間をおいてください。")
        return

    pacer = Pacer(base=tuple(cfg.get("engage", {}).get("follow_interval", [8, 20])))
    flog = _load(FOLLOW_LOG, {})
    notif_url = NOTIF.format(slug=slug)

    pw, ctx, _b = _launch()
    try:
        page = ctx.new_page()
        _record_room_stats(page, slug)
        done = 0
        idx = 0          # 何番目のアクティビティ行まで見たか
        misses = 0
        while done < can and misses < 6:
            _safe_goto(page, notif_url)
            page.wait_for_timeout(4500)
            for _ in range(3):
                page.mouse.wheel(0, 2200)
                page.wait_for_timeout(900)

            rows = _unfollowed_rows(page)
            if idx >= len(rows):
                for _ in range(4):
                    page.mouse.wheel(0, 3000)
                    page.wait_for_timeout(1200)
                rows = _unfollowed_rows(page)
                if idx >= len(rows):
                    misses += 1
                    continue
            misses = 0
            name, row_i = rows[idx]
            idx += 1
            if not name or name in flog:
                continue

            # そのユーザーのアイコンをクリック → ROOMページへ
            try:
                row = page.locator(ACTIVITY_ROW).nth(row_i)
                row.locator(".left-img").click(timeout=5000)
                page.wait_for_timeout(3500)
            except Exception:  # noqa: BLE001
                continue

            fb = page.locator(FOLLOW_BTN_SEL).first
            try:
                if fb.count() and fb.is_visible():
                    jitter(1.2)
                    fb.click(timeout=4000)
                    page.wait_for_timeout(1500)
                    done += 1
                    _bump("follow")
                    flog[name] = {"at": datetime.now().isoformat(timespec="seconds"),
                                  "back": None}
                    _save(FOLLOW_LOG, flog)
                    print(f"  + フォロー {done}/{can}  {name}")
                    if done < can:
                        pacer.wait(on_rest=lambda s: print(f"    （ひと休み {int(s)}秒）"))
                else:
                    print(f"  （{name}: 既にフォロー済み or ボタン無し）")
                    flog[name] = {"at": datetime.now().isoformat(timespec="seconds"),
                                  "back": True}
                    _save(FOLLOW_LOG, flog)
            except Exception as exc:  # noqa: BLE001
                print(f"  （スキップ {name}: {str(exc)[:40]}）")
        if done < can:
            # 通知欄（自分に反応してくれた人）の候補が尽きたら、新着の投稿をした人もフォローする。
            # 今まさに動いている人なのでフォローが返りやすい（2026-10-11 追加。通知欄だけだと1日10件前後で尽きていた）
            done += _follow_from_feed(page, can - done, flog, pacer, slug, done)
        print(f"\nフォロー回り完了: {done} 件（今日の累計 {_today_log()['follow']} 件）")
    finally:
        try:
            page.close()  # 自分のタブは閉じる（溜まると Chrome が重くなる）
        except Exception:  # noqa: BLE001
            pass
        pw.stop()


def _follow_from_feed(page, need: int, flog: dict, pacer, slug: str, start: int) -> int:
    _safe_goto(page, NEW_FEED)
    page.wait_for_timeout(5000)
    for _ in range(4):
        page.mouse.wheel(0, 2600)
        page.wait_for_timeout(1200)
    hrefs = page.evaluate(r"""()=>[...new Set([...document.querySelectorAll("a[href]")].map(a=>a.getAttribute('href'))
        .filter(h=>/^\/room_[0-9a-f]+\/items$/.test(h)))]""")
    done = 0
    for h in hrefs:
        if done >= need:
            break
        key = f"url:{h}"
        if key in flog or slug in h:
            continue
        try:
            _safe_goto(page, "https://room.rakuten.co.jp" + h)
            page.wait_for_timeout(3500)
            fb = page.locator(FOLLOW_BTN_SEL).first
            now = datetime.now().isoformat(timespec="seconds")
            if fb.count() and fb.is_visible():
                jitter(1.2)
                fb.click(timeout=4000)
                page.wait_for_timeout(1500)
                done += 1
                _bump("follow")
                flog[key] = {"at": now, "back": None, "src": "feed"}
                _save(FOLLOW_LOG, flog)
                print(f"  + フォロー {start + done}（新着の投稿者） {h}")
                if done < need:
                    pacer.wait(on_rest=lambda s: print(f"    （ひと休み {int(s)}秒）"))
            else:
                flog[key] = {"at": now, "back": True, "src": "feed"}
                _save(FOLLOW_LOG, flog)
        except Exception as exc:  # noqa: BLE001
            print(f"  （スキップ {h}: {str(exc)[:40]}）")
    return done


def _record_room_stats(page, slug: str) -> None:
    """自分のROOMのフォロワー数・フォロー数を1日1回記録する（失敗しても回りは続ける）。"""
    stats = _load(ROOM_STATS, {})
    today = date.today().isoformat()
    if today in stats:
        return
    try:
        _safe_goto(page, f"https://room.rakuten.co.jp/{slug}/items")
        page.wait_for_timeout(4000)
        text = page.inner_text("body")

        def num(label: str):
            m = re.search(label + r"\s*\n?\s*([\d,.]+)(K?)", text)
            if not m:
                return None
            v = float(m.group(1).replace(",", ""))
            return int(v * 1000) if m.group(2) else int(v)

        stats[today] = {"followers": num("フォロワー"), "following": num("フォロー(?!ワー)")}
        _save(ROOM_STATS, stats)
        print(f"  ROOMの状況: フォロワー {stats[today]['followers']} / フォロー {stats[today]['following']}")
    except Exception as exc:  # noqa: BLE001
        print(f"  （フォロワー数の記録に失敗: {str(exc)[:40]}）")


def _unfollowed_rows(page) -> list[tuple[str, int]]:
    """『未フォロー』バッジが見えているアクティビティ行の (名前, 行index)。"""
    out: list[tuple[str, int]] = []
    rows = page.locator(ACTIVITY_ROW)
    try:
        n = rows.count()
    except Exception:  # noqa: BLE001
        return out
    for i in range(min(n, 60)):
        row = rows.nth(i)
        try:
            fol = row.locator("span.follow").first
            if not fol.count() or not fol.is_visible():
                continue  # 既フォロー（ng-hide）や バッジ無し はスキップ
            nm = (row.locator("span.strong, .notice-name").first
                  .inner_text(timeout=2000) or "").strip()
        except Exception:  # noqa: BLE001
            continue
        if nm:
            out.append((nm[:40], i))
    return out


# ---------------- フォロー整理 ----------------
def _api_session(page, slug: str) -> tuple[str, str]:
    """ROOMの画面が使っている内部API用の (ユーザーID, csrfトークン) を、フォロー一覧ページの読み込みから拾う。"""
    _safe_goto(page, f"https://room.rakuten.co.jp/{slug}/followings")
    page.wait_for_timeout(4500)
    urls = page.evaluate("()=>performance.getEntriesByType('resource').map(e=>e.name)")
    for u in urls:
        m = re.search(r"/api/(\d+)/[a-z_]+\?.*csrf_tkn=([0-9a-f]+)", u)
        if m:
            return m.group(1), m.group(2)
    raise RuntimeError("ROOMのAPI情報が取れませんでした（ログイン切れの可能性）")


def _api_get(page, url: str) -> dict:
    return page.evaluate("u=>fetch(u,{credentials:'include'}).then(r=>r.json())", url)


def _api_follow(page, tok: str, object_id: str, unfollow: bool) -> bool:
    body = f"object_id={object_id}" + ("&_method=delete" if unfollow else "")
    res = page.evaluate(
        """([u,b])=>fetch(u,{method:'POST',credentials:'include',
            headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
            body:b}).then(r=>r.text().then(t=>({s:r.status,t})))""",
        [f"https://room.rakuten.co.jp/api/follow?csrf_tkn={tok}", body])
    ok = res.get("s") == 200 and '"success"' in (res.get("t") or "")
    if not ok:  # 拒否された理由を残す（頻度や原因を見て間隔を調整するため）
        print(f"    （ROOMの応答: {res.get('s')} {str(res.get('t') or '')[:160]}）")
    return ok


def _all_users(page, uid: str, tok: str, kind: str, max_pages: int = 200) -> list[dict]:
    """followers / following_users を全件取る（ページ送りは offset で効く）。"""
    out, off = [], 0
    for _ in range(max_pages):
        j = _api_get(page, f"https://room.rakuten.co.jp/api/{uid}/{kind}?api_version=2&limit=100&offset={off}&csrf_tkn={tok}")
        data = j.get("data") or []
        if not data:
            break
        seen = {x["id"] for x in out[-300:]}
        new = [u for u in data if u["id"] not in seen]
        if not new:  # 同じページが返り続ける場合の保険
            break
        out += new
        off += len(data)
        page.wait_for_timeout(250)
    return out


def unfollow_round(cfg: dict, slug: str, target: int | None = None) -> None:
    """フォロー返し＋フォローを返していない人の解除（2026-10-11 API方式で作り直し）。

    以前使っていた ROOM REPEAT 極 と同じく「フォロー返し」も行う。解除は、最近（unfollow_after_days日以内）
    フォローした相手は返ってくる可能性があるので外さない。ROOM側の制限で失敗が続いたらその回は止める。
    """
    ec = cfg.get("engage", {})
    keep_days = int(ec.get("unfollow_after_days", 7))
    caps = _caps(cfg)
    can_un = max(0, int(caps.get("unfollow_per_day", 800)) - _today_log().get("unfollow", 0))
    if target is not None:
        can_un = min(can_un, target)
    fb_day, fb_hour = _remaining(cfg, "follow")
    can_fb = min(int(ec.get("followback_per_run", 50)), fb_day, fb_hour)

    flog = _load(FOLLOW_LOG, {})
    cutoff = datetime.now() - timedelta(days=keep_days)
    recent = set()
    for k, v in flog.items():
        if not _before(v.get("at"), cutoff):
            recent.add(k.replace("url:/", "").replace("/items", ""))  # url:/room_xxx/items → room_xxx、名前はそのまま

    pw, ctx, _b = _launch()
    try:
        page = ctx.new_page()
        uid, tok = _api_session(page, slug)
        # 一覧の取得は約5分かかるので1日1回だけ取り、その日の残りの回は保存したものを使う
        cache = _load(ROOM_LISTS, {})
        if cache.get("date") == date.today().isoformat():
            followers, following = cache["followers"], cache["following"]
            print(f"  一覧は今日取得済みのものを使います（フォロワー {len(followers)} / フォロー {len(following)}）")
        else:
            followers = _all_users(page, uid, tok, "followers")
            following = _all_users(page, uid, tok, "following_users")

            def slim(us):
                return [{"id": u["id"], "username": u.get("username"), "fullname": u.get("fullname")} for u in us]

            followers, following = slim(followers), slim(following)
            _save(ROOM_LISTS, {"date": date.today().isoformat(), "followers": followers, "following": following})
        fset = {u["id"] for u in followers}
        gset = {u["id"] for u in following}
        print(f"  フォロワー {len(fset)} / フォロー {len(gset)}（相互 {len(fset & gset)}）")
        _save(ROOM_STATS_DETAIL, {"at": datetime.now().isoformat(timespec="seconds"),
                                  "followers": len(fset), "following": len(gset), "mutual": len(fset & gset)})

        # 1) フォロー返し
        done_fb = 0
        for u in followers:
            if done_fb >= can_fb:
                break
            if u["id"] in gset:
                continue
            if _api_follow(page, tok, u["id"], unfollow=False):
                done_fb += 1
                _bump("follow")
                flog[u.get("username") or u["id"]] = {"at": datetime.now().isoformat(timespec="seconds"),
                                                      "back": True, "src": "followback"}
                print(f"  ↩ フォロー返し {done_fb}  {u.get('fullname', '')[:20]}")
                page.wait_for_timeout(random.randint(1500, 4000))
            else:
                print("  フォロー返しが受け付けられなくなりました（ROOM側の制限の可能性）。この回は止めます。")
                break
        _save(FOLLOW_LOG, flog)

        # 2) フォローを返していない人の解除（古い順＝一覧の後ろから）
        stale = [u for u in reversed(following)
                 if u["id"] not in fset and u.get("username") not in recent and u.get("fullname") not in recent]
        print(f"  解除の対象: {len(stale)} 人（{keep_days}日以内にフォローした人を除く）。今回は最大 {can_un} 人")
        done, fails = 0, 0
        for u in stale:
            if done >= can_un:
                break
            if _api_follow(page, tok, u["id"], unfollow=True):
                done += 1
                fails = 0
                _bump("unfollow")
                if done % 20 == 0:
                    print(f"  - 解除 {done} 人")
                page.wait_for_timeout(random.randint(1200, 3500))
            else:
                fails += 1
                if fails >= 3:
                    print("  解除が続けて失敗しました（ROOM側の制限の可能性）。この回は止めます。")
                    break
        # 解除した人を保存済みの一覧からも消す（同じ日の次の回で二重に処理しない）
        removed = {u["id"] for u in stale[:done]} if done else set()
        if removed:
            cache = _load(ROOM_LISTS, {})
            if cache.get("date") == date.today().isoformat():
                cache["following"] = [u for u in cache["following"] if u["id"] not in removed]
                _save(ROOM_LISTS, cache)
        print(f"\nフォロー返し {done_fb} 件・フォロー解除 {done} 件（今日の解除累計 {_today_log()['unfollow']} 件）")
    finally:
        try:
            page.close()  # 自分のタブは閉じる（溜まると Chrome が重くなる）
        except Exception:  # noqa: BLE001
            pass
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
