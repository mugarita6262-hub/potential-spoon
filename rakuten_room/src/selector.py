"""候補を集めて、スコア上位 N 件を選ぶ。"""
from __future__ import annotations

import json
import random
import re

from .config import DATA_DIR
from .posted_log import recently_posted_keys
from .rakuten_api import RakutenAPI, dedupe
from .scoring import score_items


def _tag(items: list[dict], src: str) -> list[dict]:
    """どの仕組みで見つけた候補かを残す（投稿の記録 posted.json まで運び、売れた商品と突き合わせる）。"""
    for it in items:
        it.setdefault("src", src)
    return items


# 「まで・迄」の直前の日付（時刻は省略可。省略ならその日の終わり）を期限として読む
_DT_RE = re.compile(r"(?:(\d{1,2})\s*/\s*(\d{1,2})|(\d{1,2})\s*日)\s*(?:[(（][月火水木金土日][)）])?\s*"
                    r"(?:(\d{1,2})\s*[:：時]\s*(\d{2})?)?\s*(?:まで|迄)")


def sale_ended(name: str, now=None) -> bool:
    """商品名の「10/17 9:59まで」「17日09:59まで」「〜10/31 23:59迄」が、もう過ぎているか。
    2026-10-17 に「17日09:59まで」の商品を 18:40 に投稿していた（候補選びが朝の1回だけで、名前の期限を見ていなかった）。"""
    from datetime import datetime
    head = (name or "")[:80]
    if not re.search(r"まで|迄", head):
        return False
    now = now or datetime.now()
    ends = []
    for mo, md, dd, h, mi in _DT_RE.findall(head):
        try:
            month, day = (int(mo), int(md)) if mo else (now.month, int(dd))
            hour, minute = (int(h), int(mi or 0)) if h else (23, 59)
            if not (1 <= month <= 12 and 1 <= day <= 31 and hour <= 24):
                continue
            year = now.year + (1 if month < now.month - 6 else 0)
            ends.append(datetime(year, month, day, min(hour, 23), minute))
        except ValueError:
            continue
    if not ends:
        for h, mi in re.findall(r"(?<![\d/日])(\d{1,2})\s*[:：時]\s*(\d{2})?\s*(?:まで|迄)", head):
            if int(h) <= 23:
                ends.append(now.replace(hour=int(h), minute=int(mi or 0), second=0, microsecond=0))
    return bool(ends) and max(ends) < now


def gather_candidates(cfg: dict, api: RakutenAPI) -> list[dict]:
    candidates: list[dict] = []
    sources = cfg["sources"]

    if sources["ranking"]["enabled"]:
        for genre_id in sources["ranking"]["genre_ids"]:
            try:
                items = _tag(api.ranking(int(genre_id), sources["ranking"]["per_genre"]), "ranking")
                _log_ranking(items)
                candidates.extend(items)
                print(f"  ランキング genre={genre_id}: {len(items)} 件")
            except Exception as exc:  # noqa: BLE001
                print(f"  ランキング genre={genre_id} 失敗: {exc}")

    kw = sources.get("keywords") or {}
    if kw.get("enabled"):
        for word in kw.get("words", []):
            try:
                # 毎日同じ商品にならないよう、検索結果のページをランダムに選ぶ
                items = _tag(api.search(word, int(kw.get("per_keyword", 30)), sort="standard",
                                        page=random.randint(1, 10)), f"keyword:{word}")
                candidates.extend(items)
                print(f"  キーワード「{word}」: {len(items)} 件")
            except Exception as exc:  # noqa: BLE001
                print(f"  キーワード「{word}」失敗: {exc}")

    se = sources.get("seasonal") or {}
    if se.get("enabled"):
        from datetime import date as _date
        for word in (se.get("months") or {}).get(_date.today().month, []) or []:
            try:
                items = _tag(api.search(word, int(se.get("per_word", 20)), sort="-reviewCount",
                                        page=random.randint(1, 3)), f"seasonal:{word}")
                candidates.extend(items)
                print(f"  季節「{word}」: {len(items)} 件")
            except Exception as exc:  # noqa: BLE001
                print(f"  季節「{word}」失敗: {exc}")

    ss = sources.get("sold_shops") or {}
    if ss.get("enabled"):
        candidates.extend(_sold_shop_items(ss, api))

    rs = sources.get("room_search") or {}
    if rs.get("enabled"):
        candidates.extend(_tag(_room_hot_items(rs, api), "room_search"))

    from .claims_filter import drop_risky

    return drop_risky(dedupe(candidates))


def _sold_shop_items(ss: dict, api: RakutenAPI) -> list[dict]:
    """売れた商品のショップの人気商品（2026-10-18 追加）。

    楽天アフィリエイトの注文明細（data/affiliate_report.json、毎晩 room_collect が記録）の商品名から
    ショップコードを引き、data/sold_shops.json に貯める。売れた店は ROOM の読者に合っている可能性が高い。
    """
    rep_file, shop_file = DATA_DIR / "affiliate_report.json", DATA_DIR / "sold_shops.json"
    shops = json.loads(shop_file.read_text(encoding="utf-8")) if shop_file.exists() else {}
    if rep_file.exists():
        for o in json.loads(rep_file.read_text(encoding="utf-8")).get("orders", []):
            name = o.get("shop") or ""
            if not name or name in shops:
                continue
            try:
                # 先頭の【店内全品P10倍】のような宣伝のカッコ書きがあると検索に当たらない
                # 1文字の語や記号があると楽天APIが400を返すので、2文字以上の語を先頭から5つ
                q = re.sub(r"[【\[［(（][^】\]］)）]{0,40}[】\]］)）]", " ", o.get("item") or "")
                q = " ".join([w for w in re.split(r"[\s|｜/／・]+", q) if len(w) >= 2][:5])
                hit = api.search(q, 5)
                code = next((h["itemCode"].split(":")[0] for h in hit if h.get("shopName") == name), "")
            except Exception as exc:  # noqa: BLE001
                print(f"  売れた店「{name}」のショップコード取得失敗: {exc}")
                continue
            if code:
                shops[name] = code
        shop_file.write_text(json.dumps(shops, ensure_ascii=False, indent=1), encoding="utf-8")
    out = []
    for name, code in shops.items():
        try:
            items = api.search(None, int(ss.get("per_shop", 15)), shopCode=code, sort="-reviewCount")
        except Exception as exc:  # noqa: BLE001
            print(f"  売れた店「{name}」失敗: {exc}")
            continue
        out.extend(_tag(items, f"sold_shop:{name}"))
        print(f"  売れた店「{name}」: {len(items)} 件")
    return out


def _room_hot_items(rs: dict, api: RakutenAPI) -> list[dict]:
    """楽天ROOMの中で反応が出ている商品（2026-10-15 追加）。

    以前使っていたツール（ROOM REPEAT 極）は、ROOM内をキーワード検索して他の人が投稿している商品を
    コレ！していた。ROOMの利用者が実際に反応している商品なので売れやすい。ここでは商品だけを借り、
    紹介文は自分で書く（他人の文章は使わない）。ROOMの検索APIはログイン不要。
    """
    import time

    import requests

    words = list(rs.get("words") or [])
    random.shuffle(words)
    words = words[: int(rs.get("per_run_words", 6))]
    min_likes = int(rs.get("min_likes", 300))
    keys: dict[str, str] = {}
    for w in words:
        for pg in range(1, int(rs.get("pages", 2)) + 1):
            try:
                r = requests.get("https://room.rakuten.co.jp/api/collect/search", timeout=20,
                                 headers={"User-Agent": "Mozilla/5.0"},
                                 params={"api_version": 1, "currentTab": "collect", "item_page": pg,
                                         "keyword": w, "page": pg, "query": w})
                data = r.json().get("data") or []
            except Exception as exc:  # noqa: BLE001
                print(f"  ROOM検索「{w}」失敗: {exc}")
                break
            for c in data:
                it = c.get("item") or {}
                if it.get("flg_soldout") or it.get("flg_deleted") or not it.get("url"):
                    continue
                # 他の人もコレ！している（recollects）か、いいねが多いものだけ
                if (int(c.get("recollects") or 0) >= 1 or int(c.get("likes") or 0) >= min_likes) and it.get("key"):
                    keys.setdefault(it["key"], w)
            time.sleep(1.0)
    out = []
    for code in list(keys)[: int(rs.get("max_items", 40))]:
        try:
            it = api.lookup_by_code(code)
        except Exception:  # noqa: BLE001
            it = None
        if it:
            it["rank"] = 1  # ROOMで反応がある＝人気の目印として、スコアでランキング上位と同じ扱いにする
            it["source"] = "room"
            out.append(it)
    print(f"  ROOMで反応がある商品（{'・'.join(words)}）: {len(out)} 件")
    return out


RANKING_LOG = DATA_DIR / "ranking_log.json"
SALE_RE = __import__("re").compile(r"クーポン|[0-9０-９]+\s*[%％]\s*OFF|[0-9０-９]+\s*[%％]オフ|半額|"
                                    r"タイムセール|スーパーSALE|SALE|セール|値下げ|期間限定価格|特価", __import__("re").I)


def _log_ranking(items: list[dict]) -> None:
    """楽天ランキングに入った商品を日ごとに記録（何日ランクインし続けたかで「定番の売れ筋」を判定するため）。"""
    from datetime import date
    try:
        log = json.loads(RANKING_LOG.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        log = {}
    day = log.setdefault(date.today().isoformat(), {})
    for it in items:
        code = it.get("itemCode")
        if code and it.get("rank", 0) > 0:
            day[code] = min(day.get(code, 999), it["rank"])
    for k in sorted(log)[:-60]:  # 60日分だけ残す
        del log[k]
    RANKING_LOG.write_text(json.dumps(log, ensure_ascii=False), encoding="utf-8")


def ranking_days(within: int = 30) -> dict[str, int]:
    """直近 within 日のうち、楽天ランキングに入っていた日数（商品コードごと）。"""
    try:
        log = json.loads(RANKING_LOG.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    out: dict[str, int] = {}
    for day in sorted(log)[-within:]:
        for code in log[day]:
            out[code] = out.get(code, 0) + 1
    return out


def is_evergreen(it: dict, days: dict[str, int], ev: dict) -> bool:
    """ほっといても売れる定番：レビューが非常に多く評価も高い商品がランキングに入っている、
    または直近30日で何日もランキングに入り続けている。"""
    if days.get(it.get("itemCode", ""), 0) >= int(ev.get("min_rank_days", 7)):
        return True
    return (it.get("rank", 0) > 0 and it.get("reviewCount", 0) >= int(ev.get("min_reviews", 5000))
            and it.get("reviewAverage", 0) >= float(ev.get("min_average", 4.3)))


def select_items(cfg: dict, api: RakutenAPI, pool: int | None = None) -> list[dict]:
    candidates = gather_candidates(cfg, api)
    print(f"重複除去後の候補: {len(candidates)} 件")

    ev = cfg.get("evergreen") or {}
    days = ranking_days()
    for it in candidates:
        it["evergreen"] = is_evergreen(it, days, ev)
    skip = recently_posted_keys(cfg["exclude"]["reposted_within_days"])
    # 定番の売れ筋は、前回から repost_after_days 日たてばもう一度投稿する（売れ続けている商品なので）
    skip_ev = recently_posted_keys(int(ev.get("repost_after_days", 21)))
    candidates = [
        it for it in candidates
        if (it.get("itemCode") or it.get("itemUrl")) not in (skip_ev if it["evergreen"] else skip)
    ]
    print(f"投稿済みを除外後: {len(candidates)} 件（うち定番の売れ筋 {sum(it['evergreen'] for it in candidates)} 件）")

    n0 = len(candidates)
    candidates = [it for it in candidates if not sale_ended(it.get("itemName", ""))]
    if n0 != len(candidates):
        print(f"商品名のセール期限が過ぎている {n0 - len(candidates)} 件を除外")

    ranked = score_items(candidates, cfg["scoring"])
    bonus = float(ev.get("score_bonus", 0.15))
    sale_bonus = float((cfg.get("sale_boost") or {}).get("bonus", 0))
    point_bonus = {int(k): float(v) for k, v in ((cfg.get("sale_boost") or {}).get("point_bonus") or {}).items()}
    shop_bonus = float(((cfg.get("sources") or {}).get("sold_shops") or {}).get("bonus", 0))
    from datetime import datetime as _dt
    now_s = _dt.now().strftime("%Y-%m-%d %H:%M")
    for it in ranked:
        reasons = []
        if it.get("evergreen"):
            it["score"] = round(it["score"] + bonus, 4)
            reasons.append("定番")
        # 商品名の先頭にクーポン・割引・セールなどがある＝いまセールでお得な商品（期限切れは上で除外済み）
        if sale_bonus and SALE_RE.search((it.get("itemName") or "")[:60]):
            it["on_sale"] = True
            it["score"] = round(it["score"] + sale_bonus, 4)
            reasons.append("セール表記")
        # ポイント倍率（楽天APIの値。期間内のものだけ）。いちばん高い段の加点を1回だけ
        end = it.get("pointRateEndTime") or ""
        pb = max((b for r, b in point_bonus.items() if it.get("pointRate", 1) >= r), default=0)
        if pb and (not end or end[:16] >= now_s):
            it["point_up"] = True
            it["score"] = round(it["score"] + pb, 4)
            reasons.append(f"P{int(it['pointRate'])}倍")
        if shop_bonus and str(it.get("src", "")).startswith("sold_shop"):
            it["score"] = round(it["score"] + shop_bonus, 4)
            reasons.append("売れた店")
        it["reasons"] = reasons
    ranked.sort(key=lambda x: x["score"], reverse=True)
    print(f"スコア条件を満たした候補: {len(ranked)} 件")

    if pool is None:
        pool = int(cfg.get("candidate_pool", cfg["post_count"] * 3))
    # 季節もの・売れた店は点数が高く出やすく、放っておくと偏る（10/18 は季節29%・売れた2店だけで17%）。
    # 投稿は候補の上から順に出るので、上限は「1日の投稿数」に対する割合で数える
    srcs = (cfg.get("sources") or {})
    # 出どころの印 → config の sources のキー
    caps = {k: int(int(cfg.get("post_count", 100)) * float((srcs.get(ck) or {}).get("max_share", 1.0)))
            for k, ck in (("seasonal", "seasonal"), ("sold_shop", "sold_shops"))}
    used, out = dict.fromkeys(caps, 0), []
    for it in ranked:
        kind = str(it.get("src", "")).split(":")[0]
        if kind in caps:
            if used[kind] >= caps[kind]:
                continue
            used[kind] += 1
        out.append(it)
        if len(out) >= pool:
            break
    return out
