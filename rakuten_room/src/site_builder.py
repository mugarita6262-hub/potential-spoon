"""買い時ナビ（kaidokinavi.com）の静的サイトを生成する。

楽天の商品検索でジャンルごとの候補を集め、価格を毎日 price_history に記録し、
「人気ランキング」と「値下がりランキング」を数字の根拠つきで出す。
他のランキングサイトとの違いは、自前で毎日記録している価格推移を見せられること。
読み物（選び方ガイド）は content/guides/<genre>/*.md を置くと各ジャンルに載る。

サーバーで1日1回 `python -m src.main site` で再生成する（Caddyが配信）。
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from .config import DATA_DIR

SITE_NAME = "買い時ナビ"
SITE_URL = "https://kaidokinavi.com"
OUT_DIR = Path("/home/kirui/kaidokinavi")
GUIDES_DIR = Path(__file__).resolve().parent.parent / "content" / "guides"
SITE_ITEMS_FILE = DATA_DIR / "site_items.json"

GENRES = [
    {"slug": "coffee", "name": "コーヒー・お茶", "emoji": "☕",
     "lead": "毎日飲むものだから、少しでもおいしく、少しでも安く。",
     "keywords": ["コーヒー豆", "ドリップバッグ コーヒー", "紅茶 ティーバッグ", "インスタントコーヒー"],
     "a8_genres": ["飲料・カフェ"]},
    {"slug": "sleep", "name": "寝具・睡眠", "emoji": "🛏️",
     "lead": "毎晩使うものは、少し良いものを納得の値段で。",
     "keywords": ["枕", "マットレス", "掛け布団", "敷きパッド"],
     "a8_genres": ["暮らし・家事", "寝具・睡眠"]},
    {"slug": "kitchen", "name": "キッチン・家事", "emoji": "🍳",
     "lead": "毎日の台所仕事を、ちょっとラクにする道具たち。",
     "keywords": ["フライパン", "電気ケトル", "保存容器", "食器用洗剤"],
     "a8_genres": ["キッチン・家事"]},
    {"slug": "pet", "name": "ペット", "emoji": "🐾",
     "lead": "毎日のごはんとケア用品は、続けやすさと値段のバランスで。",
     "keywords": ["ドッグフード", "キャットフード", "猫砂", "ペット おやつ"],
     "a8_genres": ["ペット"]},
    {"slug": "water", "name": "水・飲料", "emoji": "💧",
     "lead": "重くてかさばる飲み物こそ、まとめ買いの単価で差がつきます。",
     "keywords": ["ミネラルウォーター 2L", "炭酸水 500ml", "お茶 ペットボトル", "野菜ジュース"],
     "a8_genres": ["飲料・カフェ", "水・飲料"]},
    {"slug": "rice", "name": "お米・食品", "emoji": "🍚",
     "lead": "値動きの大きいお米は、買うタイミングで年間の出費が変わります。",
     "keywords": ["お米 10kg", "無洗米", "パックご飯", "レトルトカレー"],
     "a8_genres": ["食品・宅食", "お米・食品"]},
    {"slug": "contact", "name": "コンタクトレンズ", "emoji": "👁️",
     "lead": "毎月買うものだから、同じレンズを少しでも安く。",
     "keywords": ["ワンデー コンタクト", "2ウィーク コンタクト", "カラコン ワンデー", "コンタクト 保存液"],
     "a8_genres": ["コンタクト"]},
    {"slug": "baby", "name": "ベビー・おむつ", "emoji": "👶",
     "lead": "おむつやおしりふきは、まとめ買いのタイミングが家計の味方です。",
     "keywords": ["おむつ テープ", "おむつ パンツ", "おしりふき", "粉ミルク"],
     "a8_genres": ["ベビー・キッズ"]},
]

MIN_REVIEWS = 20
MIN_AVG = 3.8
DROP_MIN_PCT = 5.0
TOP_N = 10


# ---------------------------------------------------------------- データ収集
def collect(api) -> dict[str, list[dict]]:
    """ジャンルごとに楽天で商品を集め、価格を記録する。{slug: [item, ...]} を保存して返す。"""
    from .price_history import record_snapshot
    from .rakuten_api import dedupe

    result: dict[str, list[dict]] = {}
    for g in GENRES:
        items: list[dict] = []
        for kw in g["keywords"]:
            try:
                items += [{**it, "keyword": kw} for it in api.search(kw, 30)]
            except Exception as exc:  # noqa: BLE001
                print(f"  検索失敗 {kw}: {exc}")
            time.sleep(1.2)  # 楽天APIの呼び出し間隔
        items = [it for it in dedupe(items)
                 if it["reviewCount"] >= MIN_REVIEWS and it["reviewAverage"] >= MIN_AVG]
        record_snapshot(items)
        result[g["slug"]] = items
        print(f"  {g['name']}: {len(items)}件")
        if os.environ.get("YAHOO_APP_ID"):
            yitems = []
            for kw in g["keywords"]:
                try:
                    yitems += [{**it, "keyword": kw} for it in yahoo_search(kw, 30)]
                except Exception as exc:  # noqa: BLE001
                    print(f"  Yahoo検索失敗 {kw}: {exc}")
                time.sleep(1.2)
            seen: set[str] = set()
            yitems = [it for it in yitems if not (it["itemCode"] in seen or seen.add(it["itemCode"]))
                      and it["reviewCount"] >= MIN_REVIEWS and it["reviewAverage"] >= MIN_AVG]
            record_snapshot(yitems)
            result[f"yahoo:{g['slug']}"] = yitems
            print(f"  {g['name']}（Yahoo!）: {len(yitems)}件")
    SITE_ITEMS_FILE.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def yahoo_search(query: str, n: int = 30) -> list[dict]:
    """Yahoo!ショッピングの商品検索（レビュー件数順）。楽天の商品と同じ形の辞書で返す。
    Client IDはURLパラメータだと403になるため、ヘッダー（User-Agent）で渡す。"""
    import requests

    r = requests.get("https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch",
                     params={"query": query, "results": n, "sort": "-review_count"},
                     headers={"User-Agent": f"Yahoo AppID: {os.environ['YAHOO_APP_ID']}"}, timeout=20)
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        rev = h.get("review") or {}
        out.append({
            "itemCode": f"yahoo:{h['code']}", "itemName": h.get("name", ""),
            "itemUrl": h.get("url", ""), "affiliateUrl": h.get("url", ""),
            "price": int(h.get("price") or 0), "shopName": (h.get("seller") or {}).get("name", ""),
            "reviewCount": int(rev.get("count") or 0), "reviewAverage": float(rev.get("rate") or 0),
            "imageUrl": (h.get("image") or {}).get("medium", ""), "mall": "yahoo",
        })
    return out


# ---------------------------------------------------------------- ランキング
def _popularity(it: dict) -> float:
    return it["reviewAverage"] * math.log10(it["reviewCount"] + 1)


def _history(it: dict, hist: dict) -> list[dict]:
    return hist.get(it.get("itemCode") or it.get("itemUrl"), [])


def _enrich(it: dict, hist: dict) -> dict:
    from .price_history import price_drop
    rows = _history(it, hist)
    info = price_drop(it, lookback_days=30)
    prices = [r["price"] for r in rows]
    return {**it, **info, "history": rows,
            "days": len(rows), "low": min(prices) if prices else it["price"],
            "high": max(prices) if prices else it["price"]}


def rankings(items: list[dict], hist: dict) -> tuple[list[dict], list[dict]]:
    rich = [_enrich(it, hist) for it in items]
    popular = sorted(rich, key=_popularity, reverse=True)[:TOP_N]
    drops = [it for it in rich if it["drop_pct"] >= DROP_MIN_PCT and it["days"] >= 2]
    drops.sort(key=lambda x: (x["drop_pct"], _popularity(x)), reverse=True)
    return popular, drops[:TOP_N]


# ---------------------------------------------------------------- 表示用の共通部品
E = html.escape
ASSETS_DIR = Path(__file__).resolve().parent.parent / "site_assets"
GENRE_BY_SLUG = {g["slug"]: g for g in GENRES}
GENRE_IMG = {g["slug"]: g["slug"] for g in GENRES}
GA4_ID = "G-MJGWNG8KND"
GA4_TAG = f"""<script async src="https://www.googletagmanager.com/gtag/js?id={GA4_ID}"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}
gtag('js',new Date());gtag('config','{GA4_ID}');
document.addEventListener('click',function(e){{var a=e.target.closest('a[rel~="sponsored"]');if(!a)return;
var h=a.hostname,net=/a8\\.net/.test(h)?'a8':(/rakuten/.test(h)?'rakuten':(/yahoo|valuecommerce/.test(h)?'yahoo':'other'));
var it=a.closest('.item');var n=it?it.querySelector('.item-name'):null;
gtag('event','affiliate_click',{{network:net,link_text:(n?n.textContent:a.textContent).trim().slice(0,90),
page_path:location.pathname,section:(a.closest('section')||{{}}).id||''}});}});</script>"""
# Yahoo!ショッピングは、バリューコマースでサイトが承認されて LinkSwitch の vc_pid を .env の
# VC_LINKSWITCH_PID に入れた時だけ表示する（それまでは素のリンクになり報酬が付かないため）。
# LinkSwitchタグがページ内の素のYahoo!ショッピングURLを自動でアフィリエイトリンクに変える。
def yahoo_enabled() -> bool:
    return bool(os.environ.get("VC_LINKSWITCH_PID")) or os.environ.get("SITE_YAHOO_PREVIEW") == "1"


def _linkswitch_tag() -> str:
    pid = os.environ.get("VC_LINKSWITCH_PID", "")
    if not pid:
        return ""
    return (f'<script>var vc_pid = "{E(pid)}";</script>'
            '<script src="//aml.valuecommerce.com/vcdal.js" async></script>')


YAHOO_CREDIT = ('<p><!-- Begin Yahoo! JAPAN Web Services Attribution Snippet -->'
                '<a href="https://developer.yahoo.co.jp/sitemap/" target="_blank" rel="noopener">Webサービス by Yahoo! JAPAN</a>'
                '<!-- End Yahoo! JAPAN Web Services Attribution Snippet --></p>')
PUBLISHER = {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL,
             "logo": {"@type": "ImageObject", "url": f"{SITE_URL}/img/icon-512.png"}}


def _short_name(name: str, n: int = 52) -> str:
    name = re.sub(r"[【\[［(（][^】\]］)）]{0,40}[】\]］)）]", " ", name)  # 宣伝用のカッコ書きを除く
    name = re.sub(r"[＼\\／/★☆◆◇■□●○※!！]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:n] + ("…" if len(name) > n else "")


def _yen(n: int) -> str:
    return f"{n:,}円"


def _sparkline(rows: list[dict]) -> str:
    if len(rows) < 2:
        return '<span class="muted">価格記録 1日目</span>'
    prices = [r["price"] for r in rows][-60:]
    lo, hi = min(prices), max(prices)
    w, h = 132, 34
    span = (hi - lo) or 1
    pts = [(i * w / (len(prices) - 1), h - 4 - (p - lo) * (h - 8) / span) for i, p in enumerate(prices)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"0,{h} " + line + f" {w},{h}"
    lx, ly = pts[-1]
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="直近{len(prices)}日の価格推移。最安{lo:,}円、最高{hi:,}円">'
            f'<polygon points="{area}" class="spark-area"/>'
            f'<polyline points="{line}" class="spark-line"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3" class="spark-dot"/></svg>')


def _buy_url(it: dict) -> str:
    return it.get("affiliateUrl") or it["itemUrl"]


def _item_card(rank: int, it: dict, mode: str) -> str:
    url = E(_buy_url(it))
    medal = {1: "gold", 2: "silver", 3: "bronze"}.get(rank, "")
    badges = []
    if it.get("is_all_time_low") and it["days"] >= 7:
        badges.append('<span class="badge badge-low">記録上の最安値</span>')
    if mode == "drop":
        badges.append(f'<span class="badge badge-drop">{it["drop_pct"]:.0f}%値下がり</span>')
    stars = f'<span class="stars">★{it["reviewAverage"]:.2f}</span><span class="muted">（{it["reviewCount"]:,}件）</span>'
    was = (f'<s class="was">{_yen(it["reference_price"])}</s>'
           if mode == "drop" and it["reference_price"] > it["price"] else "")
    rng = (f'<span class="muted">記録{it["days"]}日・最安{_yen(it["low"])}・最高{_yen(it["high"])}</span>'
           if it["days"] >= 2 else "")
    img = (f'<img src="{E(it["imageUrl"])}" alt="{E(_short_name(it["itemName"], 40))}" '
           f'loading="lazy" decoding="async" width="112" height="112">'
           if it.get("imageUrl") else '<div class="noimg"></div>')
    is_yahoo = it.get("mall") == "yahoo"
    buttons = (f'<a class="btn-buy btn-yahoo" href="{url}" rel="nofollow sponsored noopener" target="_blank">Yahoo!で見る</a>'
               if is_yahoo else
               f'<a class="btn-buy" href="{url}" rel="nofollow sponsored noopener" target="_blank">楽天で見る</a>')
    if not is_yahoo and yahoo_enabled():
        q = E(quote(_short_name(it["itemName"], 40).rstrip("…")))
        buttons += (f'<a class="btn-sub" href="https://shopping.yahoo.co.jp/search?p={q}" '
                    f'rel="nofollow sponsored noopener" target="_blank">Yahoo!で探す</a>')
    return f"""
<li class="item" id="{mode}-{rank}">
  <div class="rank {medal}">{rank}</div>
  <a class="thumb" href="{url}" rel="nofollow sponsored noopener" target="_blank">{img}</a>
  <div class="item-body">
    <h3 class="item-name"><a href="{url}" rel="nofollow sponsored noopener" target="_blank">{E(_short_name(it["itemName"]))}</a></h3>
    <div class="badges">{"".join(badges)}</div>
    <div class="price-row"><span class="price">{it["price"]:,}<small>円</small></span>{was}</div>
    <div class="rating">{stars}</div>
    <div class="trend">{_sparkline(it["history"])}{rng}</div>
    <div class="item-foot"><span class="muted shop">{E(it.get("shopName", ""))}</span>
      <span class="btns">{buttons}</span></div>
  </div>
</li>"""


def _a8_links(genre: dict) -> list[dict]:
    try:
        from .a8_selector import load_links
        return [l for l in load_links() if l.get("genre") in genre["a8_genres"]]
    except Exception:  # noqa: BLE001
        return []


def _svc_name(name: str, n: int = 60) -> str:
    """A8の案件名は【】内がブランド名のことが多いので、括弧だけ外して中身は残す。"""
    name = re.sub(r"[【】\[\]「」]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:n] + ("…" if len(name) > n else "")


def _svc_card(l: dict) -> str:
    """サービス1件のカード。買い時ナビ用のバナー素材(site_banner)があれば画像つきで出す。"""
    bn = l.get("site_banner") or {}
    url = E(bn.get("href") or l["url"])
    rel = 'rel="nofollow sponsored noopener" target="_blank"'
    banner = ""
    if bn.get("img"):
        banner = (f'<a class="svc-banner" href="{url}" {rel}><img src="{E(bn["img"])}" width="{bn.get("width", 300)}" '
                  f'height="{bn.get("height", 250)}" alt="{E(_svc_name(l["program_name"], 40))}" loading="lazy"></a>'
                  f'<img class="px" src="{E(bn["pixel"])}" width="1" height="1" alt="">')
    return (f'<li class="svc">{banner}<div class="svc-body"><b>{E(l.get("site_name") or _svc_name(l["program_name"]))}</b>'
            f'<span>{E((l.get("site_note") or l.get("note", ""))[:80])}</span></div>'
            f'<a class="btn-svc" href="{url}" {rel}>公式サイトを見る</a></li>')


def _a8_box(genre: dict) -> str:
    links = _a8_links(genre)
    if not links:
        return ""
    cards = "".join(_svc_card(l) for l in links)
    return f"""
<section class="services" id="services" aria-labelledby="h-services">
  <div class="services-head"><span class="pr">PR</span>
  <h2 id="h-services">{E(genre["name"])}を探している人におすすめのサービス</h2></div>
  <p class="basis">お店で買うより続けやすい、定期便・お試しセットなどのサービスです。</p>
  <ul class="svc-list">{cards}</ul>
</section>"""


def _guides(slug: str) -> list[dict]:
    out = []
    d = GUIDES_DIR / slug
    if not d.exists():
        return out
    for p in sorted(d.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        title = lines[0].lstrip("# ").strip() if lines else p.stem
        desc = next((l.strip() for l in lines[1:] if l.strip() and not l.startswith("#")), title)
        out.append({"slug": p.stem, "title": title, "desc": desc[:110], "md": text,
                    "updated": datetime.fromtimestamp(p.stat().st_mtime).date().isoformat()})
    return out


def _md_to_html(md: str) -> tuple[str, list[tuple[str, str]]]:
    """見出し・段落・箇条書き・表・太字・リンクの最小限Markdown変換。(html, 目次) を返す。"""
    out, toc, in_list, table = [], [], False, []

    def flush_table() -> None:
        if not table:
            return
        rows = [r for r in table if not re.fullmatch(r"\|?[\s:\-|]+\|?", r)]
        cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
        head = "".join(f"<th>{_inline(c)}</th>" for c in cells[0])
        body = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in cells[1:])
        out.append(f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
        table.clear()

    for line in md.splitlines()[1:]:  # 1行目はタイトル
        s = line.rstrip()
        if s.startswith("|"):
            table.append(s); continue
        flush_table()
        if s.startswith("- "):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{_inline(s[2:])}</li>"); continue
        if in_list:
            out.append("</ul>"); in_list = False
        if s.startswith("### "):
            out.append(f"<h3>{_inline(s[4:])}</h3>")
        elif s.startswith("## "):
            hid = f"s{len(toc) + 1}"
            toc.append((hid, s[3:]))
            out.append(f'<h2 id="{hid}">{_inline(s[3:])}</h2>')
        elif s.startswith("> "):
            out.append(f'<p class="point">{_inline(s[2:])}</p>')
        elif s:
            out.append(f"<p>{_inline(s)}</p>")
    flush_table()
    if in_list:
        out.append("</ul>")
    return "\n".join(out), toc


def _inline(s: str) -> str:
    s = E(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"\[(.+?)\]\((https?://[^)\s]+|/[^)\s]*)\)",
                  lambda m: (f'<a href="{m.group(2)}">{m.group(1)}</a>' if m.group(2).startswith("/") else
                             f'<a href="{m.group(2)}" rel="nofollow sponsored noopener" target="_blank">{m.group(1)}</a>'), s)


def _jsonld(*objs: dict) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(o, ensure_ascii=False)}</script>'
                   for o in objs if o)


def _breadcrumb(items: list[tuple[str, str]]) -> tuple[str, dict]:
    """[(名前, パス), ...] → (HTML, JSON-LD)"""
    html_ = '<nav class="crumbs" aria-label="パンくずリスト"><ol>' + "".join(
        (f'<li><a href="{p}">{E(n)}</a></li>' if i < len(items) - 1 else f'<li aria-current="page">{E(n)}</li>')
        for i, (n, p) in enumerate(items)) + "</ol></nav>"
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": f"{SITE_URL}{p}"}
        for i, (n, p) in enumerate(items)]}
    return html_, ld


def _itemlist_ld(name: str, items: list[dict], path: str) -> dict:
    if not items:
        return {}
    return {"@context": "https://schema.org", "@type": "ItemList", "name": name,
            "url": f"{SITE_URL}{path}", "numberOfItems": len(items),
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1,
                 "item": {"@type": "Product", "name": _short_name(it["itemName"], 120),
                          "image": it.get("imageUrl") or None,
                          "offers": {"@type": "Offer", "price": it["price"], "priceCurrency": "JPY",
                                     "url": it["itemUrl"], "availability": "https://schema.org/InStock",
                                     "seller": {"@type": "Organization", "name": it.get("shopName", "")}}}}
                for i, it in enumerate(items)]}


def _faq(qas: list[tuple[str, str]]) -> tuple[str, dict]:
    html_ = ('<section class="section" id="faq" aria-labelledby="h-faq"><h2 id="h-faq">よくある質問</h2>'
             + "".join(f'<details class="qa"><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q, a in qas)
             + "</section>")
    ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qas]}
    return html_, ld


# ---------------------------------------------------------------- デザイン
CSS = """
:root{--bg:#f7f3ec;--surface:#fff;--ink:#28231d;--sub:#6f655a;--muted:#958a7d;--line:#e9e0d3;
--brand:#b8562f;--brand-dark:#93421f;--brand-soft:#fbeee6;--green:#2c7a67;--green-soft:#e5f2ee;
--gold:#c9a227;--silver:#9aa3ab;--bronze:#b07a4f;--radius:18px;--shadow:0 1px 2px rgba(40,35,29,.04),0 6px 24px rgba(40,35,29,.06)}
*{box-sizing:border-box}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.75;font-size:16px;
font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP","Yu Gothic UI",Meiryo,system-ui,sans-serif;
font-feature-settings:"palt" 1}
a{color:inherit}
img{max-width:100%;display:block}
.wrap{width:100%;max-width:1000px;margin:0 auto;padding:0 18px}
.muted{color:var(--muted);font-size:13px}
.prbar{background:#2d2822;color:#e9e0d3;font-size:12px;text-align:center;padding:5px 12px}
.site-header{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.88);
backdrop-filter:saturate(1.4) blur(10px);-webkit-backdrop-filter:saturate(1.4) blur(10px);border-bottom:1px solid var(--line)}
.site-header .hrow{display:flex;align-items:center;gap:16px;min-height:58px}
.site-header .hnav{padding-bottom:6px}
.sbox{margin-left:auto;display:flex;align-items:center;flex:0 1 380px;background:#f4efe8;border:1px solid var(--line);
border-radius:999px;padding:0 6px 0 14px}
.sbox input{flex:1;min-width:0;border:0;background:transparent;font:inherit;font-size:15px;padding:9px 0;outline:none;color:var(--ink)}
.sbox button{border:0;background:var(--brand);color:#fff;border-radius:999px;padding:6px 14px;font:inherit;font-size:14px;font-weight:700;cursor:pointer}
.sbox:focus-within{border-color:var(--brand);background:#fff}
.logo{display:flex;align-items:center;gap:8px;font-weight:800;font-size:19px;text-decoration:none;white-space:nowrap}
.logo svg{flex:none}
.logo em{font-style:normal;color:var(--brand)}
.gnav{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none}
.gnav::-webkit-scrollbar{display:none}
.gnav a{white-space:nowrap;font-size:14px;font-weight:600;text-decoration:none;padding:7px 12px;border-radius:999px;color:var(--sub)}
.gnav a:hover,.gnav a[aria-current]{background:var(--brand-soft);color:var(--brand-dark)}
/* hero */
.hero{position:relative;color:#fff;background:#3a2e24 center/cover no-repeat;isolation:isolate}
.hero::before{content:"";position:absolute;inset:0;z-index:-1;
background:linear-gradient(100deg,rgba(28,20,14,.86) 0%,rgba(28,20,14,.62) 45%,rgba(28,20,14,.15) 100%)}
.hero .wrap{padding-top:64px;padding-bottom:56px}
.hero h1{font-size:clamp(28px,5vw,44px);line-height:1.3;margin:0 0 14px;letter-spacing:.01em}
.hero p{max-width:560px;margin:0 0 22px;color:#f1e9df;font-size:clamp(15px,2.2vw,17px)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:5px 13px;font-size:13px}
.chip b{font-size:15px;margin-right:2px}
.banner{position:relative;color:#fff;background:#3a2e24 center/cover no-repeat;isolation:isolate}
.banner::before{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(0deg,rgba(28,20,14,.82),rgba(28,20,14,.35))}
.banner .wrap{padding-top:52px;padding-bottom:30px}
.banner h1{font-size:clamp(25px,4.4vw,36px);line-height:1.35;margin:6px 0 6px}
.banner p{margin:0;color:#f1e9df}
.crumbs ol{list-style:none;display:flex;flex-wrap:wrap;gap:4px;margin:0;padding:0;font-size:12px;opacity:.9}
.crumbs li+li::before{content:"›";margin-right:4px}
.crumbs a{text-decoration:none}
main{padding-bottom:40px}
/* summary (AIO) */
.summary{background:var(--surface);border:1px solid var(--line);border-left:5px solid var(--green);
border-radius:var(--radius);padding:18px 20px;margin:-22px 0 8px;position:relative;box-shadow:var(--shadow)}
.summary h2{font-size:15px;margin:0 0 6px;color:var(--green)}
.summary p{margin:0}
.summary ul{margin:8px 0 0;padding-left:20px}
.summary .stamp{display:block;margin-top:8px}
.toc-pills{display:flex;gap:8px;overflow-x:auto;padding:10px 0;scrollbar-width:none;position:sticky;
top:var(--hdr-h,108px);z-index:15;background:var(--bg);margin:0 -18px;padding-left:18px;padding-right:18px}
.toc-pills a.on{background:var(--brand);border-color:var(--brand);color:#fff}
section[id],h2[id],.item[id]{scroll-margin-top:calc(var(--hdr-h,108px) + 64px)}
.totop{position:fixed;right:16px;bottom:calc(16px + env(safe-area-inset-bottom,0px));z-index:30;width:46px;height:46px;border-radius:50%;
border:0;background:var(--ink);color:#fff;font-size:20px;box-shadow:0 6px 18px rgba(0,0,0,.2);cursor:pointer;opacity:0;pointer-events:none;transition:opacity .2s}
.totop.show{opacity:.9;pointer-events:auto}
.related .gcards{grid-template-columns:repeat(auto-fill,minmax(160px,1fr))}
.related .gcard div{padding:10px 12px}.related .gcard b{font-size:15px}
.sresult{display:grid;gap:10px;list-style:none;margin:0;padding:0}
.sresult a{display:flex;gap:12px;align-items:center;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:10px 12px;text-decoration:none}
.sresult img{width:64px;height:64px;object-fit:contain;border-radius:8px;background:#faf7f2;flex:none}
.sresult b{display:block;font-size:14px;line-height:1.5}.sresult small{color:var(--muted)}
.toc-pills a{white-space:nowrap;text-decoration:none;font-size:14px;font-weight:600;background:var(--surface);
border:1px solid var(--line);border-radius:999px;padding:7px 14px}
.toc-pills a:hover{border-color:var(--brand);color:var(--brand)}
.section{margin:28px 0}
.section>h2{font-size:clamp(20px,3vw,24px);margin:0 0 4px;line-height:1.4}
.basis{font-size:13px;color:var(--sub);margin:0 0 12px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden}
/* ranking items */
ol.items{list-style:none;margin:0;padding:0}
.item{display:grid;grid-template-columns:34px 112px 1fr;gap:14px;padding:18px;border-top:1px solid var(--line);align-items:start}
.item:first-child{border-top:0}
.rank{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;font-weight:800;
background:#f1ebe2;color:var(--sub);font-size:15px}
.rank.gold{background:var(--gold);color:#fff}.rank.silver{background:var(--silver);color:#fff}.rank.bronze{background:var(--bronze);color:#fff}
.thumb img,.noimg{width:112px;height:112px;object-fit:contain;border-radius:12px;background:#faf7f2;border:1px solid var(--line)}
.item-name{font-size:15px;line-height:1.5;margin:0 0 4px}
.item-name a{text-decoration:none}.item-name a:hover{color:var(--brand)}
.badges{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:2px}
.badge{font-size:11px;font-weight:700;border-radius:6px;padding:2px 8px}
.badge-low{background:var(--green-soft);color:var(--green)}.badge-drop{background:var(--brand-soft);color:var(--brand-dark)}
.price-row{display:flex;align-items:baseline;gap:10px}
.price{font-size:22px;font-weight:800;letter-spacing:.01em}
.price small{font-size:13px;margin-left:1px}
.was{color:var(--muted);font-size:13px}
.stars{color:#c98a12;font-weight:700;font-size:14px;margin-right:2px}
.trend{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:4px 0}
.spark{color:var(--green)}.spark-line{fill:none;stroke:var(--green);stroke-width:2;stroke-linejoin:round}
.spark-area{fill:var(--green-soft)}.spark-dot{fill:var(--green)}
.item-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:6px}
.shop{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn-buy{flex:none;background:var(--brand);color:#fff;text-decoration:none;font-weight:700;font-size:14px;
padding:9px 18px;border-radius:999px;transition:background .15s}
.btn-buy:hover{background:var(--brand-dark)}
.btns{display:flex;gap:8px;flex:none;flex-wrap:wrap;justify-content:flex-end}
.btn-yahoo{background:#d92d20}.btn-yahoo:hover{background:#b0241a}
.btn-sub{flex:none;text-decoration:none;font-weight:700;font-size:14px;padding:8px 16px;border-radius:999px;
border:1.5px solid #d92d20;color:#d92d20;background:#fff}
.btn-sub:hover{background:#fdf0ef}
.mall-tag{display:inline-block;font-size:11px;font-weight:700;color:#d92d20;border:1px solid #d92d20;border-radius:4px;padding:0 5px;margin-left:6px;vertical-align:middle}
.empty{padding:22px;color:var(--sub);text-align:center}
/* compare table */
.table-wrap{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius)}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:560px}
th,td{padding:11px 14px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#faf6f0;font-size:13px;color:var(--sub);white-space:nowrap}
tr:last-child td{border-bottom:0}
td.num{text-align:right;white-space:nowrap}
/* genre cards */
.gcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}
.gcard{display:block;text-decoration:none;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
overflow:hidden;box-shadow:var(--shadow);transition:transform .15s,box-shadow .15s}
.gcard:hover{transform:translateY(-3px);box-shadow:0 10px 30px rgba(40,35,29,.12)}
.gcard img{aspect-ratio:16/9;object-fit:cover;width:100%;height:auto}
.gcard div{padding:14px 16px 16px}
.gcard b{display:block;font-size:17px}
.gcard span{font-size:13px;color:var(--sub)}
.gcard .tag{display:inline-block;margin-top:8px;font-size:12px;font-weight:700;color:var(--brand-dark);background:var(--brand-soft);
border-radius:6px;padding:1px 8px}
/* services, guides, faq */
.services{margin:28px 0;background:linear-gradient(135deg,#fff6ef 0%,#fdebdf 100%);border:2px solid #f0c9b0;
border-radius:var(--radius);padding:20px clamp(14px,3vw,24px);box-shadow:var(--shadow)}
.services-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.services h2{font-size:clamp(18px,2.6vw,22px);margin:0;line-height:1.4}
.svc-list{list-style:none;margin:10px 0 0;padding:0;display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.svc{background:#fff;border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:12px;justify-content:space-between;
border:1px solid #f0d7c6}
.svc b{display:block;font-size:16px;line-height:1.45}
.svc-banner{display:block;text-align:center;line-height:0}
.svc-banner img{max-width:100%;height:auto;border-radius:10px}
.svc .px{position:absolute;width:1px;height:1px;opacity:0}
.svc span{display:block;font-size:13px;color:var(--sub);margin-top:4px}
.btn-svc{display:block;text-align:center;background:var(--green);color:#fff;text-decoration:none;font-weight:700;
padding:11px 16px;border-radius:999px}
.btn-svc:hover{background:#225f50}
.service-list,.guide-list{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.service-list a,.guide-list a{display:block;text-decoration:none;background:var(--surface);border:1px solid var(--line);
border-radius:14px;padding:14px 16px}
.service-list a:hover,.guide-list a:hover{border-color:var(--brand)}
.service-list b,.guide-list b{display:block}
.service-list span,.guide-list span{display:block;font-size:13px;color:var(--sub)}
.pr{display:inline-block;font-size:11px;border:1px solid var(--muted);color:var(--muted);border-radius:4px;padding:0 5px;
vertical-align:middle;font-weight:600}
.qa{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:0 16px;margin-bottom:10px}
.qa summary{cursor:pointer;font-weight:700;padding:14px 0;list-style:none}
.qa summary::before{content:"Q. ";color:var(--brand)}
.qa summary::-webkit-details-marker{display:none}
.qa p{margin:0 0 14px;color:var(--sub)}
/* article */
.article{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:clamp(18px,4vw,36px);box-shadow:var(--shadow)}
.article h2{font-size:21px;margin:34px 0 10px;padding-left:12px;border-left:4px solid var(--brand);line-height:1.45}
.article h3{font-size:17px;margin:24px 0 6px}
.article table{min-width:0}
.article .table-wrap{margin:12px 0}
.article .point{background:var(--green-soft);border-radius:12px;padding:12px 16px}
.toc{background:#faf6f0;border-radius:12px;padding:14px 18px;margin:16px 0}
.toc b{font-size:14px}.toc ol{margin:6px 0 0;padding-left:20px;font-size:14px}
.byline{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-bottom:10px}
/* footer */
.site-footer{background:#2d2822;color:#cfc4b6;font-size:13px;padding:36px 0 28px;margin-top:40px}
.site-footer a{color:#f1e9df}
.fcols{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-bottom:18px}
.fcols b{color:#fff;display:block;margin-bottom:6px}
.fcols ul{list-style:none;margin:0;padding:0;line-height:2}
.fcols a{text-decoration:none}
@media (max-width:560px){
.site-header .hrow{gap:10px;min-height:52px}
.logo span{display:none}
.sbox{flex:1 1 auto}
.item{grid-template-columns:28px 84px 1fr;gap:10px;padding:14px}
.rank{width:28px;height:28px;font-size:13px}
.thumb img,.noimg{width:84px;height:84px}
.item-foot{flex-wrap:wrap}.btns{width:100%}.btn-buy,.btn-sub{flex:1;text-align:center}
}
"""

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#b8562f"/><path d="M14 20 L28 34 L36 26 L50 42" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><path d="M40 42 H50 V32" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>"""
LOGO_SVG = ('<svg width="30" height="30" viewBox="0 0 64 64" aria-hidden="true">'
            '<rect width="64" height="64" rx="16" fill="#b8562f"/>'
            '<path d="M14 20 L28 34 L36 26 L50 42" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
            '<path d="M40 42 H50 V32" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _page(title: str, body: str, desc: str, path: str, *, current: str = "",
          og_image: str = "/img/hero.jpg", ld: str = "", og_type: str = "website", noindex: bool = False) -> str:
    robots = "noindex,follow" if noindex else "index,follow,max-image-preview:large"
    cur_attr = ' aria-current="page"'
    nav = "".join(f'<a href="/{g["slug"]}/"{cur_attr if g["slug"] == current else ""}>'
                  f'{E(g["name"])}</a>' for g in GENRES)
    full_title = f"{title}｜{SITE_NAME}" if title != SITE_NAME else f"{SITE_NAME}｜毎日の価格記録で買い時が分かる"
    yahoo_credit = (YAHOO_CREDIT if yahoo_enabled() else "")
    footer_genres = "".join(f'<li><a href="/{g["slug"]}/">{E(g["name"])}の買い時</a></li>' for g in GENRES)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{E(full_title)}</title>
<meta name="description" content="{E(desc)}">
<link rel="canonical" href="{SITE_URL}{path}">
<meta name="robots" content="{robots}">
<meta name="theme-color" content="#b8562f">
<meta property="og:site_name" content="{SITE_NAME}"><meta property="og:type" content="{og_type}">
<meta property="og:title" content="{E(full_title)}"><meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{SITE_URL}{path}"><meta property="og:image" content="{SITE_URL}{og_image}">
<meta property="og:locale" content="ja_JP"><meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/img/apple-touch-icon.png">
<link rel="stylesheet" href="/style.css?v={date.today().strftime('%Y%m%d')}">
{GA4_TAG}
{_linkswitch_tag()}
{ld}
</head><body>
<div class="prbar">当サイトはアフィリエイト広告（楽天アフィリエイト・A8.net）を利用しています</div>
<header class="site-header" id="hdr">
<div class="wrap hrow"><a class="logo" href="/" aria-label="{SITE_NAME} トップ">{LOGO_SVG}<span>買い時<em>ナビ</em></span></a>
<form class="sbox" action="/search/" method="get" role="search"><input type="search" name="q" placeholder="商品名・ジャンルで探す" aria-label="サイト内検索" enterkeyhint="search"><button type="submit">検索</button></form></div>
<div class="wrap hnav"><nav class="gnav" aria-label="ジャンル">{nav}</nav></div>
</header>
<main>{body}</main>
<button class="totop" type="button" aria-label="ページ上部へ" onclick="scrollTo({{top:0,behavior:'smooth'}})">↑</button>
<script>(function(){{var h=document.getElementById('hdr'),r=document.documentElement;
function s(){{r.style.setProperty('--hdr-h',h.offsetHeight+'px')}}s();addEventListener('resize',s);
var t=document.querySelector('.totop');addEventListener('scroll',function(){{t.classList.toggle('show',scrollY>600)}},{{passive:true}});
var links=[].slice.call(document.querySelectorAll('.toc-pills a'));if(!links.length||!('IntersectionObserver'in window))return;
var io=new IntersectionObserver(function(es){{es.forEach(function(e){{if(e.isIntersecting){{links.forEach(function(a){{
var on=a.getAttribute('href')==='#'+e.target.id;a.classList.toggle('on',on);if(on)a.scrollIntoView({{block:'nearest',inline:'center'}})}})}}}})}},
{{rootMargin:'-45% 0px -50% 0px'}});links.forEach(function(a){{var el=document.querySelector(a.getAttribute('href'));if(el)io.observe(el)}});}})();</script>
<footer class="site-footer"><div class="wrap">
<div class="fcols">
<div><b>{SITE_NAME}</b><p>暮らしの定番アイテムの価格を毎日記録して、値下がりと評判から「買い時」をお知らせします。</p></div>
<div><b>ジャンル</b><ul>{footer_genres}</ul></div>
<div><b>サイトについて</b><ul><li><a href="/about/">運営者・ランキングの根拠</a></li><li><a href="/privacy/">プライバシーポリシー</a></li></ul></div>
</div>
<p>掲載価格は更新時点のものです。最新の価格・在庫は各ショップのページでご確認ください。</p>
{yahoo_credit}
<p><!-- Rakuten Web Services BEGIN --><a href="https://webservice.rakuten.co.jp/" target="_blank" rel="noopener">Supported by Rakuten Developers</a><!-- Rakuten Web Services END --></p>
<p>© {date.today().year} {SITE_NAME}</p>
</div></footer>
</body></html>
"""


def _genre_tag(data: tuple) -> str:
    _, popular, drops = data
    return f"{len(drops)}件 値下がり中" if drops else f"評判ランキング TOP{len(popular)}"


def _related_genres(cur: str, genre_data: dict) -> str:
    cards = "".join(
        f'<a class="gcard" href="/{g["slug"]}/"><img src="/img/{GENRE_IMG[g["slug"]]}.jpg" alt="" loading="lazy" '
        f'width="1200" height="675"><div><b>{g["emoji"]} {E(g["name"])}</b>'
        f'<span class="tag">{_genre_tag(genre_data[g["slug"]])}</span></div></a>'
        for g in GENRES if g["slug"] != cur)
    return (f'<section class="section related" aria-labelledby="h-other"><h2 id="h-other">ほかのジャンルの買い時もチェック</h2>'
            f'<div class="gcards">{cards}</div></section>')


SEARCH_JS = r"""(function(){var q=new URLSearchParams(location.search).get('q')||'',inp=document.getElementById('sq'),
out=document.getElementById('sres'),msg=document.getElementById('smsg');inp.value=q;
document.querySelectorAll('.sbox input').forEach(function(i){i.value=q});
function norm(s){return(s||'').toLowerCase().replace(/[！-～]/g,function(c){return String.fromCharCode(c.charCodeAt(0)-0xfee0)})
.replace(/[ァ-ヶ]/g,function(c){return String.fromCharCode(c.charCodeAt(0)-0x60)}).replace(/\s+/g,' ')}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
fetch('/search.json').then(function(r){return r.json()}).then(function(d){function run(){var w=norm(inp.value).trim().split(' ').filter(Boolean);
if(!w.length){msg.textContent='キーワードを入力してください。';out.innerHTML='';return}
var hit=d.filter(function(x){var s=norm(x.t+' '+x.k);return w.every(function(v){return s.indexOf(v)>=0})});
hit.sort(function(a,b){return a.o-b.o});msg.textContent='「'+inp.value+'」の検索結果：'+hit.length+'件';
out.innerHTML=hit.slice(0,60).map(function(x){return'<li><a href="'+esc(x.u)+'">'+(x.i?'<img src="'+esc(x.i)+'" alt="" loading="lazy">':'')+
'<div><b>'+esc(x.t)+'</b><small>'+esc(x.s)+'</small></div></a></li>'}).join('')||'';
if(typeof gtag==='function')gtag('event','search',{search_term:inp.value})}
run();document.getElementById('sform').addEventListener('submit',function(e){e.preventDefault();
history.replaceState(null,'','?q='+encodeURIComponent(inp.value));run()})})})();"""


def _search_index(genre_data: dict) -> list[dict]:
    """サイト内検索の索引（ジャンル・ガイド・ランキング掲載商品）。o は表示順の優先度。"""
    idx = []
    for g in GENRES:
        idx.append({"t": f"{g['name']}の買い時", "s": f"ジャンル｜{g['lead']}", "u": f"/{g['slug']}/",
                    "k": " ".join(g["keywords"]), "i": f"/img/{GENRE_IMG[g['slug']]}.jpg", "o": 0})
        for x in _guides(g["slug"]):
            idx.append({"t": x["title"], "s": f"選び方ガイド｜{x['desc']}", "u": f"/{g['slug']}/{x['slug']}/",
                        "k": g["name"], "i": "", "o": 1})
        _, popular, drops = genre_data[g["slug"]]
        seen = set()
        for mode, lst in (("drop", drops), ("pop", popular)):
            for rank, it in enumerate(lst, 1):
                if it["itemCode"] in seen:
                    continue
                seen.add(it["itemCode"])
                label = f"{it['drop_pct']:.0f}%値下がり中" if mode == "drop" else f"評判ランキング{rank}位"
                idx.append({"t": _short_name(it["itemName"], 60), "s": f"{g['name']}｜{it['price']:,}円｜{label}",
                            "u": f"/{g['slug']}/#{mode}-{rank}", "k": f"{g['name']} {it.get('shopName', '')}",
                            "i": it.get("imageUrl", ""), "o": 2 if mode == "drop" else 3})
    return idx


def _write(path: str, content: str) -> None:
    p = OUT_DIR / path.strip("/") / "index.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _items_list(items: list[dict], mode: str, empty: str) -> str:
    if not items:
        return f'<div class="panel"><p class="empty">{empty}</p></div>'
    return '<div class="panel"><ol class="items">' + "".join(
        _item_card(i + 1, it, mode) for i, it in enumerate(items)) + "</ol></div>"


def _compare_table(items: list[dict]) -> str:
    rows = "".join(
        f'<tr><td>{i + 1}</td><td><a href="{E(_buy_url(it))}" rel="nofollow sponsored noopener" target="_blank">'
        f'{E(_short_name(it["itemName"], 34))}</a></td><td class="num">{_yen(it["price"])}</td>'
        f'<td class="num">★{it["reviewAverage"]:.2f}</td><td class="num">{it["reviewCount"]:,}件</td>'
        f'<td class="num">{_yen(it["low"]) if it["days"] >= 2 else "記録中"}</td></tr>'
        for i, it in enumerate(items))
    return (f'<div class="table-wrap"><table><caption class="muted" style="text-align:left;padding:10px 14px">'
            f'評判ランキング上位の比較（価格は更新時点）</caption><thead><tr><th>順位</th><th>商品</th><th>価格</th>'
            f'<th>評価</th><th>レビュー数</th><th>記録上の最安</th></tr></thead><tbody>{rows}</tbody></table></div>')


def _genre_summary(g: dict, popular: list[dict], drops: list[dict], all_items: list[dict], updated: str) -> tuple[str, str]:
    """ページ冒頭の結論（AIに引用されやすい要約）と、metaに使う短文。"""
    top = popular[0] if popular else None
    lines = []
    if top:
        lines.append(f'評判が最も良いのは「{_short_name(top["itemName"], 40)}」（★{top["reviewAverage"]:.2f}、'
                     f'レビュー{top["reviewCount"]:,}件、{_yen(top["price"])}）。')
    if drops:
        d = drops[0]
        lines.append(f'値下がり中の商品は{len(drops)}件で、最も下がっているのは「{_short_name(d["itemName"], 40)}」'
                     f'（直近30日の参考価格{_yen(d["reference_price"])}→{_yen(d["price"])}、{d["drop_pct"]:.0f}%下落）。')
    else:
        lines.append("現在、直近30日の最高値から5%以上値下がりしている商品はありません。")
    lis = "".join(f"<li>{E(l)}</li>" for l in lines)
    html_ = (f'<section class="summary" aria-labelledby="h-summary"><h2 id="h-summary">結論：{E(updated)}時点の'
             f'{E(g["name"])}の買い時</h2><ul>{lis}</ul>'
             f'<span class="stamp muted">対象：楽天市場の{E(g["name"])} {len(all_items)}商品（★{MIN_AVG}以上・'
             f'レビュー{MIN_REVIEWS}件以上）を毎日記録</span></section>')
    return html_, " ".join(lines)


def _genre_faq(g: dict, popular: list[dict], drops: list[dict], updated: str) -> list[tuple[str, str]]:
    qas = []
    if popular:
        t = popular[0]
        qas.append((f"{g['name']}で一番評判が良い商品は？",
                    f"{updated}時点では「{_short_name(t['itemName'], 50)}」です。楽天市場でのレビュー評価は"
                    f"★{t['reviewAverage']:.2f}、レビュー数は{t['reviewCount']:,}件で、価格は{_yen(t['price'])}でした。"))
    if drops:
        d = drops[0]
        qas.append((f"今、値下がりしている{g['name']}は？",
                    f"{updated}時点で直近30日の最高値から5%以上下がっている商品は{len(drops)}件です。最も下がっているのは"
                    f"「{_short_name(d['itemName'], 50)}」で、{_yen(d['reference_price'])}から{_yen(d['price'])}"
                    f"（{d['drop_pct']:.0f}%）に下がっています。"))
    else:
        qas.append((f"今、{g['name']}は買い時？",
                    f"{updated}時点では、記録している商品に直近30日の最高値から5%以上の値下がりはありません。"
                    "急ぎでなければ、楽天のお買い物マラソンや5と0のつく日など、ポイントが多く付く日を待つのも一つの方法です。"))
    qas.append(("ランキングはどうやって決めていますか？",
                f"楽天市場のレビュー評価が★{MIN_AVG}以上かつレビュー{MIN_REVIEWS}件以上の商品を対象に、評価の高さと"
                "レビュー件数を掛け合わせた点数で機械的に順位を付けています。広告料によって順位を上下させることはありません。"))
    qas.append(("価格はどのくらいの頻度で更新されますか？",
                "毎日1回、楽天市場の価格を記録して更新しています。記録した日数が増えるほど、値下がりの判定や"
                "価格推移のグラフが正確になります。"))
    return qas


def build(items_by_genre: dict[str, list[dict]] | None = None) -> int:
    """サイト一式を書き出す。書き出したページ数を返す。"""
    import shutil

    from .price_history import load_all

    if items_by_genre is None:
        items_by_genre = json.loads(SITE_ITEMS_FILE.read_text(encoding="utf-8"))
    hist = load_all()
    now = datetime.now()
    updated = f"{now.year}年{now.month}月{now.day}日"
    today = date.today().isoformat()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "style.css").write_text(CSS, encoding="utf-8")
    (OUT_DIR / "favicon.svg").write_text(ICON_SVG, encoding="utf-8")
    if (ASSETS_DIR / "img").exists():
        shutil.copytree(ASSETS_DIR / "img", OUT_DIR / "img", dirs_exist_ok=True)

    pages = 0
    genre_data = {}
    yahoo_data: dict[str, list[dict]] = {}
    total_items = 0
    for g in GENRES:
        items = items_by_genre.get(g["slug"], [])
        total_items += len(items)
        popular, drops = rankings(items, hist)
        genre_data[g["slug"]] = (items, popular, drops)
        ypop = rankings(items_by_genre.get(f"yahoo:{g['slug']}", []), hist)[0] if yahoo_enabled() else []
        yahoo_data[g["slug"]] = ypop

    # ---- ジャンルページ
    for g in GENRES:
        items, popular, drops = genre_data[g["slug"]]
        path = f"/{g['slug']}/"
        img = GENRE_IMG.get(g["slug"], "hero")
        guides = _guides(g["slug"])
        crumbs, crumbs_ld = _breadcrumb([("ホーム", "/"), (f"{g['name']}の買い時", path)])
        summary, summary_text = _genre_summary(g, popular, drops, items, updated)
        faq_html, faq_ld = _faq(_genre_faq(g, popular, drops, updated))
        ypop = yahoo_data.get(g["slug"], [])
        yahoo_html = ""
        if ypop:
            yahoo_html = f"""
<section class="section" id="yahoo" aria-labelledby="h-yahoo">
  <h2 id="h-yahoo">Yahoo!ショッピングで評判の良い{E(g["name"])} TOP{len(ypop)}</h2>
  <p class="basis">Yahoo!ショッピングのレビュー評価（★{MIN_AVG}以上・{MIN_REVIEWS}件以上）を、楽天と同じ基準で順位付けしています（{updated}更新）。楽天のランキングと見比べて、安い方・ポイントが多い方で選べます。</p>
  {_items_list(ypop, "yahoo", "データを準備中です。")}
</section>"""
        pills = ['<a href="#drops">値下がり中</a>', '<a href="#ranking">評判ランキング</a>',
                 '<a href="#compare">比較表</a>']
        if ypop:
            pills.insert(2, '<a href="#yahoo">Yahoo!で比較</a>')
        if guides:
            pills.append('<a href="#guides">選び方ガイド</a>')
        pills.append('<a href="#faq">よくある質問</a>')
        guides_html = ""
        if guides:
            guides_html = ('<section class="section" id="guides" aria-labelledby="h-guides"><h2 id="h-guides">選び方ガイド</h2>'
                           '<ul class="guide-list">' + "".join(
                               f'<li><a href="{path}{E(x["slug"])}/"><b>{E(x["title"])}</b><span>{E(x["desc"])}</span></a></li>'
                               for x in guides) + "</ul></section>")
        body = f"""
<section class="banner" style="background-image:url('/img/{img}.jpg')"><div class="wrap">
{crumbs}<h1>{E(g["name"])}の買い時｜値下がり・評判ランキング</h1><p>{E(g["lead"])}</p></div></section>
<div class="wrap">
{summary}
<nav class="toc-pills" aria-label="ページ内リンク">{"".join(pills)}</nav>
<section class="section" id="drops" aria-labelledby="h-drops">
  <h2 id="h-drops">今、値下がりしている{E(g["name"])}</h2>
  <p class="basis">直近30日に記録した最高値と比べて{DROP_MIN_PCT:.0f}%以上安くなっている商品を、下落率の大きい順に表示しています（{updated}更新）。</p>
  {_items_list(drops, "drop", "今は大きく値下がりしている商品はありません。価格は毎日記録しているので、下がったものがあればここに並びます。")}
</section>
<section class="section" id="ranking" aria-labelledby="h-ranking">
  <h2 id="h-ranking">評判の良い{E(g["name"])}ランキング TOP{len(popular)}</h2>
  <p class="basis">楽天市場のレビュー評価（★{MIN_AVG}以上・{MIN_REVIEWS}件以上）を対象に、評価の高さとレビュー件数を掛け合わせた点数で順位付けしています（{updated}更新）。広告料による順位の上下はありません。</p>
  {_items_list(popular, "pop", "データを準備中です。")}
</section>
{_a8_box(g)}
{yahoo_html}
<section class="section" id="compare" aria-labelledby="h-compare">
  <h2 id="h-compare">ランキング上位の比較表</h2>
  {_compare_table(popular)}
</section>
{guides_html}
{faq_html}
{_related_genres(g["slug"], genre_data)}
</div>"""
        ld = _jsonld(crumbs_ld, faq_ld,
                     _itemlist_ld(f"評判の良い{g['name']}ランキング", popular, path),
                     {"@context": "https://schema.org", "@type": "CollectionPage",
                      "name": f"{g['name']}の買い時｜値下がり・評判ランキング", "url": f"{SITE_URL}{path}",
                      "dateModified": today, "description": summary_text, "publisher": PUBLISHER})
        _write(path, _page(f"{g['name']}の買い時｜値下がり・評判ランキング【{now.year}年{now.month}月】", body,
                           f"{summary_text} 楽天市場の{g['name']}{len(items)}商品の価格を毎日記録して、値下がり中の商品と評判の良い商品をまとめています。"[:150],
                           path, current=g["slug"], og_image=f"/img/{img}.jpg", ld=ld))
        pages += 1

        # ---- ガイド記事
        for x in guides:
            apath = f"{path}{x['slug']}/"
            art_html, toc = _md_to_html(x["md"])
            crumbs_a, crumbs_a_ld = _breadcrumb([("ホーム", "/"), (f"{g['name']}の買い時", path), (x["title"], apath)])
            toc_html = ('<nav class="toc" aria-label="目次"><b>目次</b><ol>' + "".join(
                f'<li><a href="#{hid}">{E(t)}</a></li>' for hid, t in toc) + "</ol></nav>") if len(toc) >= 2 else ""
            body = f"""
<section class="banner" style="background-image:url('/img/{img}.jpg')"><div class="wrap">
{crumbs_a}<h1>{E(x["title"])}</h1></div></section>
<div class="wrap">
<article class="article" style="margin-top:24px">
<div class="byline"><span>更新日：<time datetime="{x["updated"]}">{x["updated"]}</time></span><span>書いた人：aki.h190（{SITE_NAME}運営）</span><span class="pr">PR含む</span></div>
{toc_html}
{art_html}
</article>
{_a8_box(g)}
<section class="section" aria-labelledby="h-rel"><h2 id="h-rel">いま評判の良い{E(g["name"])} TOP5</h2>
<p class="basis">{updated}更新。詳しくは<a href="{path}#ranking">{E(g["name"])}の評判ランキング</a>へ。</p>
{_items_list(popular[:5], "pop", "データを準備中です。")}</section>
{_related_genres(g["slug"], genre_data)}
</div>"""
            ld = _jsonld(crumbs_a_ld, {"@context": "https://schema.org", "@type": "Article", "headline": x["title"],
                                        "description": x["desc"], "datePublished": x["updated"], "dateModified": x["updated"],
                                        "image": f"{SITE_URL}/img/{img}.jpg", "mainEntityOfPage": f"{SITE_URL}{apath}",
                                        "author": {"@type": "Person", "name": "aki.h190", "url": f"{SITE_URL}/about/"},
                                        "publisher": PUBLISHER})
            _write(apath, _page(x["title"], body, x["desc"], apath, current=g["slug"],
                                og_image=f"/img/{img}.jpg", ld=ld, og_type="article"))
            pages += 1

    # ---- トップページ
    top_drops = sorted(((g, d) for g in GENRES for d in genre_data[g["slug"]][2][:3]),
                       key=lambda gd: gd[1]["drop_pct"], reverse=True)[:8]
    cards = "".join(
        f'<a class="gcard" href="/{g["slug"]}/"><img src="/img/{GENRE_IMG[g["slug"]]}.jpg" alt="" loading="lazy" '
        f'width="1200" height="675"><div><b>{E(g["name"])}</b><span>{E(g["lead"])}</span>'
        f'<span class="tag">{_genre_tag(genre_data[g["slug"]])}</span></div></a>' for g in GENRES)
    guides_all = [(g, x) for g in GENRES for x in _guides(g["slug"])]
    guides_home = ('<section class="section" aria-labelledby="h-g"><h2 id="h-g">選び方ガイド</h2><ul class="guide-list">'
                   + "".join(f'<li><a href="/{g["slug"]}/{E(x["slug"])}/"><b>{E(x["title"])}</b><span>{E(g["name"])}｜{E(x["desc"])}</span></a></li>'
                             for g, x in guides_all[:6]) + "</ul></section>") if guides_all else ""
    n_drops = sum(len(v[2]) for v in genre_data.values())
    home_summary = (f"{updated}時点で、{len(GENRES)}ジャンル{total_items}商品の価格を記録しています。"
                    f"直近30日の最高値から5%以上値下がりしている商品は{n_drops}件です。")
    body = f"""
<section class="hero" style="background-image:url('/img/hero.jpg')"><div class="wrap">
<h1>毎日の価格記録で、<br>暮らしの「買い時」が分かる。</h1>
<p>水・お米・コンタクト・おむつ・コーヒー・寝具など、毎日の暮らしの定番の価格を毎日記録。値下がりしているものと、評判の良いものを、数字の根拠つきでまとめています。</p>
<div class="chips"><span class="chip"><b>{total_items}</b>商品を記録中</span><span class="chip"><b>{n_drops}</b>件が値下がり中</span><span class="chip">毎朝更新</span></div>
</div></section>
<div class="wrap">
<section class="summary" aria-labelledby="h-sum"><h2 id="h-sum">今日のまとめ（{updated}）</h2><p>{E(home_summary)}</p></section>
<section class="section" aria-labelledby="h-genres"><h2 id="h-genres">ジャンルから探す</h2><div class="gcards">{cards}</div></section>
<section class="section" aria-labelledby="h-drops"><h2 id="h-drops">今日の値下がりピックアップ</h2>
<p class="basis">各ジャンルで直近30日の最高値から{DROP_MIN_PCT:.0f}%以上下がった商品（{updated}更新）。</p>
{_items_list([d for _, d in top_drops], "drop", "今日は大きな値下がりはありません。価格は毎日記録しています。")}</section>
{guides_home}
</div>"""
    ld = _jsonld({"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME, "url": SITE_URL,
                  "description": home_summary, "inLanguage": "ja", "publisher": PUBLISHER})
    _write("/", _page(SITE_NAME, body, f"{home_summary} 楽天市場の暮らしの定番アイテムの価格を毎日記録して、値下がりと評判から買い時をお知らせします。",
                      "/", ld=ld))
    pages += 1

    # ---- 運営情報・プライバシー
    about = f"""
<section class="banner" style="background-image:url('/img/hero.jpg')"><div class="wrap">
{_breadcrumb([("ホーム", "/"), ("このサイトについて", "/about/")])[0]}<h1>このサイトについて</h1></div></section>
<div class="wrap"><article class="article" style="margin-top:24px">
<h2>買い時ナビとは</h2>
<p>水・お米・コンタクトレンズ・おむつ・コーヒー・寝具・キッチン用品・ペット用品など、毎日の暮らしで使う定番アイテムの価格を毎日記録し、「今が買い時か」を数字で判断できるようにまとめたサイトです。値下がりの判定には、当サイトが独自に毎日記録している価格データを使っています。</p>
<h2>ランキングの根拠</h2>
<ul>
<li>商品データは楽天市場（楽天ウェブサービスAPI）から毎日取得しています。</li>
<li>「値下がり」は、当サイトが記録した価格のうち直近30日の最高値と、更新時点の価格を比べた下落率です。記録が2日分以上ある商品が対象です。</li>
<li>「記録上の最安値」は、当サイトが記録を始めてからの最安値であることを示します（記録7日以上の商品のみ表示）。</li>
<li>「評判の良い」ランキングは、レビュー評価★{MIN_AVG}以上・レビュー{MIN_REVIEWS}件以上の商品を、評価の高さとレビュー件数を掛け合わせた点数で並べています。</li>
<li>順位はこれらの数値だけで機械的に決めており、広告料などによって順位を上下させることはありません。</li>
</ul>
<h2>広告について</h2>
<p>当サイトのリンクの多くはアフィリエイトリンク（楽天アフィリエイト・A8.net）です。リンク経由で購入・申込があった場合、当サイトに報酬が支払われることがあります。報酬の有無はランキングの順位に影響しません。</p>
<h2>運営者</h2>
<p>aki.h190。Instagram・Threadsで「日々のくらしで見つけた、これ良かった」を発信しています。</p>
<h2>写真について</h2>
<p>当サイトのイメージ写真は <a href="https://unsplash.com/" target="_blank" rel="noopener">Unsplash</a> のフリー素材を使用しています。商品画像は楽天市場の各ショップのものです。</p>
</article></div>"""
    _write("/about/", _page("このサイトについて・ランキングの根拠", about, "買い時ナビの運営者、ランキングと値下がり判定の根拠、広告についての説明", "/about/",
                           ld=_jsonld(_breadcrumb([("ホーム", "/"), ("このサイトについて", "/about/")])[1],
                                      {"@context": "https://schema.org", "@type": "AboutPage", "name": "このサイトについて",
                                       "url": f"{SITE_URL}/about/", "publisher": PUBLISHER})))
    yahoo_privacy = ('<tr><td>株式会社バリューコマース（Yahoo!ショッピングのアフィリエイト）</td>'
                     '<td>リンクのクリック情報、Cookie識別子</td><td>成果報酬の計測</td></tr>') if yahoo_enabled() else ""
    privacy = f"""
<section class="banner" style="background-image:url('/img/hero.jpg')"><div class="wrap">
{_breadcrumb([("ホーム", "/"), ("プライバシーポリシー", "/privacy/")])[0]}<h1>プライバシーポリシー</h1></div></section>
<div class="wrap"><article class="article" style="margin-top:24px">
<p>当サイトでは、お問い合わせ等で取得した個人情報を、本人の同意なく第三者に提供することはありません。</p>
<p>当サイトはアフィリエイトプログラム（楽天アフィリエイト・A8.net）を利用しています。リンクのクリックや購入の計測のため、提携先がCookieを使用することがあります。Cookieはブラウザの設定で無効にできます。</p>
<h2>アクセス解析ツールについて</h2>
<p>当サイトでは、サイトの利用状況を把握して改善するために、Google LLCのアクセス解析ツール「Googleアナリティクス」を使用しています。Googleアナリティクスは、Cookieを使って、閲覧したページ、滞在時間、どのページのリンクがクリックされたかといった情報を収集します。収集される情報に、氏名など個人を特定する情報は含まれません。</p>
<p>この機能はブラウザのCookieを無効にすることで拒否できます。詳しくは<a href="https://marketingplatform.google.com/about/analytics/terms/jp/" target="_blank" rel="noopener">Googleアナリティクス利用規約</a>と<a href="https://policies.google.com/technologies/partner-sites?hl=ja" target="_blank" rel="noopener">Googleのサービスを使用するサイトやアプリから収集した情報のGoogleによる使用</a>をご確認ください。</p>
<h2>外部送信される情報について</h2>
<table><thead><tr><th>送信先</th><th>送信される情報</th><th>目的</th></tr></thead><tbody>
<tr><td>Google LLC（Googleアナリティクス）</td><td>閲覧ページのURL、リファラー、端末・ブラウザの情報、Cookie識別子、クリックしたリンク</td><td>アクセス解析・サイト改善</td></tr>{yahoo_privacy}
<tr><td>楽天グループ株式会社（楽天アフィリエイト）</td><td>リンクのクリック情報、Cookie識別子</td><td>成果報酬の計測</td></tr>
<tr><td>株式会社ファンコミュニケーションズ（A8.net）</td><td>リンクのクリック情報、Cookie識別子</td><td>成果報酬の計測</td></tr>
</tbody></table>
<p>当サイトの掲載内容は正確さに努めていますが、価格・在庫等は変動するため、購入前に必ず販売ページでご確認ください。</p>
</article></div>"""
    _write("/privacy/", _page("プライバシーポリシー", privacy, "買い時ナビのプライバシーポリシー。個人情報とCookieの扱い、アフィリエイトについて", "/privacy/",
                             ld=_jsonld(_breadcrumb([("ホーム", "/"), ("プライバシーポリシー", "/privacy/")])[1])))
    pages += 2

    # ---- サイト内検索
    (OUT_DIR / "search.json").write_text(json.dumps(_search_index(genre_data), ensure_ascii=False,
                                                    separators=(",", ":")), encoding="utf-8")
    search = f"""
<div class="wrap"><section class="section" style="margin-top:24px"><h1 style="font-size:24px">サイト内検索</h1>
<form class="sbox" id="sform" role="search" style="margin:12px 0 16px;max-width:560px"><input type="search" id="sq" name="q" placeholder="商品名・ジャンルで探す" aria-label="検索キーワード"><button type="submit">検索</button></form>
<p class="basis" id="smsg">読み込み中…</p><ul class="sresult" id="sres"></ul>
<p class="basis" style="margin-top:20px">見つからないときは、ジャンルから探してみてください。</p></section>
{_related_genres("", genre_data)}</div>
<script>{SEARCH_JS}</script>"""
    _write("/search/", _page("サイト内検索", search, "買い時ナビのサイト内検索", "/search/", noindex=True))
    pages += 1

    # ---- sitemap / robots / llms.txt
    urls = ["/", "/about/", "/privacy/"] + [f"/{g['slug']}/" for g in GENRES] + [
        f"/{g['slug']}/{x['slug']}/" for g, x in guides_all]
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               + "".join(f"<url><loc>{SITE_URL}{u}</loc><lastmod>{today}</lastmod></url>" for u in urls)
               + "</urlset>\n")
    (OUT_DIR / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (OUT_DIR / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")
    llms = [f"# {SITE_NAME}", "",
            f"> 楽天市場の暮らしの定番アイテム（{'・'.join(g['name'] for g in GENRES)}）の価格を毎日記録し、"
            "値下がり中の商品と評判の良い商品を数字の根拠つきでまとめた日本語の比較サイト。", "",
            f"- 最終更新: {today}", f"- 記録中の商品数: {total_items}",
            "- 値下がりの定義: 直近30日に記録した最高値と比べて5%以上安い", f"- 評判ランキングの対象: 楽天のレビュー★{MIN_AVG}以上かつ{MIN_REVIEWS}件以上",
            "", "## ジャンル別ページ"]
    for g in GENRES:
        items, popular, drops = genre_data[g["slug"]]
        top = f"評判1位: {_short_name(popular[0]['itemName'], 40)}（★{popular[0]['reviewAverage']:.2f}）" if popular else ""
        llms.append(f"- [{g['name']}の買い時]({SITE_URL}/{g['slug']}/): 値下がり中{len(drops)}件。{top}")
    if guides_all:
        llms += ["", "## 選び方ガイド"] + [f"- [{x['title']}]({SITE_URL}/{g['slug']}/{x['slug']}/): {x['desc']}"
                                       for g, x in guides_all]
    llms += ["", "## 運営情報", f"- [ランキングの根拠と運営者]({SITE_URL}/about/)"]
    (OUT_DIR / "llms.txt").write_text("\n".join(llms) + "\n", encoding="utf-8")
    return pages
