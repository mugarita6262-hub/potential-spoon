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
import re
import time
from datetime import date, datetime
from pathlib import Path

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
    SITE_ITEMS_FILE.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


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


# ---------------------------------------------------------------- HTML部品
E = html.escape


def _short_name(name: str, n: int = 52) -> str:
    name = re.sub(r"[【\[［(（][^】\]］)）]{0,40}[】\]］)）]", " ", name)  # 宣伝用のカッコ書きを除く
    name = re.sub(r"\s+", " ", name).strip()
    return name[:n] + ("…" if len(name) > n else "")


def _sparkline(rows: list[dict]) -> str:
    if len(rows) < 2:
        return '<span class="spark-none">価格記録 1日目</span>'
    prices = [r["price"] for r in rows][-60:]
    lo, hi = min(prices), max(prices)
    w, h = 120, 32
    span = (hi - lo) or 1
    pts = " ".join(
        f"{i * w / (len(prices) - 1):.1f},{h - 3 - (p - lo) * (h - 6) / span:.1f}"
        for i, p in enumerate(prices))
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="直近{len(prices)}日の価格推移（最安{lo:,}円・最高{hi:,}円）">'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="2"/></svg>')


def _item_card(rank: int, it: dict, mode: str) -> str:
    url = it.get("affiliateUrl") or it["itemUrl"]
    badges = []
    if it.get("is_all_time_low") and it["days"] >= 7:
        badges.append('<span class="badge low">記録上の最安値</span>')
    if mode == "drop":
        badges.append(f'<span class="badge drop">{it["drop_pct"]:.0f}%下落</span>')
    sub = (f'直近30日の参考価格 {it["reference_price"]:,}円 → 今 {it["price"]:,}円'
           if mode == "drop" else
           f'★{it["reviewAverage"]:.2f}（レビュー{it["reviewCount"]:,}件）')
    img = (f'<img src="{E(it["imageUrl"])}" alt="" loading="lazy" width="96" height="96">'
           if it.get("imageUrl") else '<div class="noimg"></div>')
    return f"""
<li class="item">
  <div class="rank">{rank}</div>
  <a class="thumb" href="{E(url)}" rel="nofollow sponsored noopener" target="_blank">{img}</a>
  <div class="body">
    <a class="name" href="{E(url)}" rel="nofollow sponsored noopener" target="_blank">{E(_short_name(it["itemName"]))}</a>
    <div class="badges">{"".join(badges)}</div>
    <div class="price">{it["price"]:,}<small>円</small></div>
    <div class="sub">{E(sub)}</div>
    <div class="trend">{_sparkline(it["history"])}{
      f'<span class="range">記録{it["days"]}日 / 最安{it["low"]:,}円・最高{it["high"]:,}円</span>'
      if it["days"] >= 2 else ""}</div>
    <div class="shop">{E(it.get("shopName", ""))}</div>
  </div>
</li>"""


def _a8_box(genre: dict) -> str:
    try:
        from .a8_selector import load_links
        links = [l for l in load_links() if l.get("genre") in genre["a8_genres"]]
    except Exception:  # noqa: BLE001
        links = []
    if not links:
        return ""
    lis = "".join(
        f'<li><a href="{E(l["url"])}" rel="nofollow sponsored noopener" target="_blank">'
        f'{E(l["program_name"][:60])}</a><span>{E(l.get("note", "")[:60])}</span></li>'
        for l in links)
    return f"""
<section class="card services">
  <h2>あわせて検討したいサービス <span class="pr">PR</span></h2>
  <ul>{lis}</ul>
</section>"""


def _guides(slug: str) -> list[dict]:
    out = []
    d = GUIDES_DIR / slug
    if not d.exists():
        return out
    for p in sorted(d.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip() if text else p.stem
        out.append({"slug": p.stem, "title": title, "md": text})
    return out


def _md_to_html(md: str) -> str:
    """見出し・段落・箇条書き・太字・リンクだけの最小限のMarkdown変換。"""
    out, in_list = [], False
    for line in md.splitlines()[1:]:  # 1行目はタイトル
        s = line.rstrip()
        if s.startswith("- "):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{_inline(s[2:])}</li>"); continue
        if in_list:
            out.append("</ul>"); in_list = False
        if s.startswith("### "):
            out.append(f"<h3>{_inline(s[4:])}</h3>")
        elif s.startswith("## "):
            out.append(f"<h2>{_inline(s[3:])}</h2>")
        elif s:
            out.append(f"<p>{_inline(s)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _inline(s: str) -> str:
    s = E(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"\[(.+?)\]\((https?://[^)\s]+)\)",
                  r'<a href="\2" rel="nofollow sponsored noopener" target="_blank">\1</a>', s)


# ---------------------------------------------------------------- ページ
CSS = """
:root{--bg:#fbf7f1;--card:#fff;--ink:#2f2a24;--muted:#8a7f72;--line:#ece3d6;
--accent:#c2643c;--accent2:#2f7d6d;--low:#2f7d6d;--drop:#c2643c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:system-ui,-apple-system,"Hiragino Sans","Yu Gothic UI",sans-serif;line-height:1.7}
a{color:inherit}
.wrap{max-width:860px;margin:0 auto;padding:0 16px}
header.site{background:#fff;border-bottom:1px solid var(--line)}
header.site .wrap{display:flex;align-items:center;justify-content:space-between;gap:12px;
padding-top:12px;padding-bottom:12px;flex-wrap:wrap}
.logo{font-weight:800;font-size:20px;text-decoration:none;letter-spacing:.02em}
.logo span{color:var(--accent)}
nav.genres{display:flex;gap:6px;flex-wrap:wrap}
nav.genres a{font-size:13px;text-decoration:none;padding:4px 10px;border-radius:999px;
background:var(--bg);border:1px solid var(--line)}
.prbar{font-size:12px;color:var(--muted);background:#fff7ef;border-bottom:1px solid var(--line);
padding:6px 0}
h1{font-size:24px;margin:24px 0 4px}
.lead{color:var(--muted);margin:0 0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:16px 0}
.card h2{font-size:18px;margin:0 0 4px}
.basis{font-size:12px;color:var(--muted);margin:0 0 8px}
ol.items{list-style:none;margin:0;padding:0}
.item{display:grid;grid-template-columns:28px 96px 1fr;gap:12px;padding:12px 0;
border-top:1px solid var(--line)}
.item:first-child{border-top:0}
.rank{font-weight:800;font-size:18px;color:var(--accent);text-align:center}
.thumb img,.noimg{width:96px;height:96px;object-fit:contain;border-radius:10px;background:#faf6f0}
.name{font-weight:700;text-decoration:none;display:block}
.name:hover{text-decoration:underline}
.price{font-size:20px;font-weight:800}
.price small{font-size:12px;margin-left:2px}
.sub,.shop,.range,.spark-none{font-size:12px;color:var(--muted)}
.trend{display:flex;align-items:center;gap:8px;flex-wrap:wrap;color:var(--accent2)}
.badge{display:inline-block;font-size:11px;font-weight:700;color:#fff;border-radius:6px;
padding:1px 7px;margin-right:4px}
.badge.low{background:var(--low)} .badge.drop{background:var(--drop)}
.empty{color:var(--muted);font-size:14px}
.gcards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.gcard{display:block;text-decoration:none;background:#fff;border:1px solid var(--line);
border-radius:14px;padding:16px}
.gcard b{display:block;font-size:17px;margin-top:4px}
.gcard span{font-size:13px;color:var(--muted)}
.services ul,.guides ul{margin:0;padding-left:18px}
.services li span{display:block;font-size:12px;color:var(--muted)}
.pr{font-size:11px;border:1px solid var(--muted);color:var(--muted);border-radius:4px;padding:0 4px;
vertical-align:middle}
article.guide h2{font-size:19px;margin-top:28px}
footer.site{margin:40px 0 0;padding:24px 0;border-top:1px solid var(--line);font-size:12px;
color:var(--muted);background:#fff}
footer.site a{margin-right:12px}
@media (max-width:480px){.item{grid-template-columns:22px 72px 1fr}.thumb img,.noimg{width:72px;height:72px}}
"""


def _page(title: str, body: str, desc: str, path: str) -> str:
    nav = "".join(f'<a href="/{g["slug"]}/">{g["emoji"]} {E(g["name"])}</a>' for g in GENRES)
    full_title = f"{title}｜{SITE_NAME}" if title != SITE_NAME else SITE_NAME
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(full_title)}</title>
<meta name="description" content="{E(desc)}">
<link rel="canonical" href="{SITE_URL}{path}">
<link rel="stylesheet" href="/style.css">
</head><body>
<div class="prbar"><div class="wrap">当サイトはアフィリエイト広告（楽天アフィリエイト・A8.net）を利用しています。</div></div>
<header class="site"><div class="wrap">
<a class="logo" href="/">買い時<span>ナビ</span></a>
<nav class="genres">{nav}</nav>
</div></header>
<main class="wrap">{body}</main>
<footer class="site"><div class="wrap">
<a href="/about/">このサイトについて・ランキングの根拠</a><a href="/privacy/">プライバシーポリシー</a>
<p>掲載価格は更新時点のものです。最新の価格・在庫は各ショップのページでご確認ください。</p>
<p><!-- Rakuten Web Services BEGIN --><a href="https://webservice.rakuten.co.jp/" target="_blank" rel="noopener">Supported by Rakuten Developers</a><!-- Rakuten Web Services END --></p>
<p>© {date.today().year} {SITE_NAME}</p>
</div></footer>
</body></html>
"""


def _write(path: str, content: str) -> None:
    p = OUT_DIR / path.strip("/") / "index.html" if not path.endswith(".css") else OUT_DIR / path.strip("/")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _ranking_sections(genre: dict, popular: list[dict], drops: list[dict], updated: str) -> str:
    drop_html = ("<ol class=\"items\">" + "".join(_item_card(i + 1, it, "drop") for i, it in enumerate(drops))
                 + "</ol>") if drops else (
        '<p class="empty">今は大きく値下がりしている商品はありません。'
        '価格は毎日記録しているので、下がったものがあればここに並びます。</p>')
    pop_html = "<ol class=\"items\">" + "".join(
        _item_card(i + 1, it, "pop") for i, it in enumerate(popular)) + "</ol>"
    return f"""
<section class="card">
  <h2>📉 今、値下がりしている{E(genre["name"])}</h2>
  <p class="basis">直近30日に記録した価格の最高値と比べて{DROP_MIN_PCT:.0f}%以上安くなっている商品を、下落率の大きい順に表示（{updated}更新）。</p>
  {drop_html}
</section>
<section class="card">
  <h2>⭐ 評判の良い{E(genre["name"])} ランキング</h2>
  <p class="basis">楽天市場のレビュー評価（★{MIN_AVG}以上・{MIN_REVIEWS}件以上）を対象に、評価の高さとレビュー件数を掛け合わせた点数で順位付け（{updated}更新）。広告料による順位の上下はありません。</p>
  {pop_html}
</section>"""


def build(items_by_genre: dict[str, list[dict]] | None = None) -> int:
    """サイト一式を書き出す。書き出したページ数を返す。"""
    from .price_history import load_all

    if items_by_genre is None:
        items_by_genre = json.loads(SITE_ITEMS_FILE.read_text(encoding="utf-8"))
    hist = load_all()
    now = datetime.now()
    updated = f"{now.year}年{now.month}月{now.day}日"
    pages = 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "style.css").write_text(CSS, encoding="utf-8")

    top_drops: list[tuple[dict, dict]] = []
    for g in GENRES:
        popular, drops = rankings(items_by_genre.get(g["slug"], []), hist)
        top_drops += [(g, d) for d in drops[:3]]
        guides = _guides(g["slug"])
        guide_list = "".join(f'<li><a href="/{g["slug"]}/{E(x["slug"])}/">{E(x["title"])}</a></li>'
                             for x in guides)
        guides_html = (f'<section class="card guides"><h2>📖 選び方ガイド</h2><ul>{guide_list}</ul></section>'
                       if guides else "")
        body = (f'<h1>{g["emoji"]} {E(g["name"])}の買い時</h1><p class="lead">{E(g["lead"])}</p>'
                + guides_html + _ranking_sections(g, popular, drops, updated) + _a8_box(g))
        _write(f"/{g['slug']}/", _page(f"{g['name']}の値下がり・人気ランキング", body,
                                        f"{g['name']}の値下がり情報と評判の良い商品ランキング。毎日の価格記録から買い時が分かります。",
                                        f"/{g['slug']}/"))
        pages += 1
        for x in guides:
            art = (f'<p><a href="/{g["slug"]}/">← {E(g["name"])}の買い時へ</a></p>'
                   f'<article class="card guide"><h1>{E(x["title"])}</h1>{_md_to_html(x["md"])}</article>'
                   + _ranking_sections(g, popular[:5], drops[:5], updated) + _a8_box(g))
            _write(f"/{g['slug']}/{x['slug']}/", _page(x["title"], art, x["title"], f"/{g['slug']}/{x['slug']}/"))
            pages += 1

    top_drops.sort(key=lambda gd: gd[1]["drop_pct"], reverse=True)
    drop_list = ("<ol class=\"items\">" + "".join(_item_card(i + 1, d, "drop")
                                                  for i, (_, d) in enumerate(top_drops[:8])) + "</ol>"
                 if top_drops else '<p class="empty">今日は大きな値下がりはありません。価格は毎日記録しています。</p>')
    cards = "".join(f'<a class="gcard" href="/{g["slug"]}/">{g["emoji"]}<b>{E(g["name"])}</b>'
                    f'<span>{E(g["lead"])}</span></a>' for g in GENRES)
    home = f"""
<h1>毎日の価格記録で「買い時」が分かる</h1>
<p class="lead">楽天市場の暮らしの定番アイテムの価格を毎日記録して、値下がりしているものと評判の良いものをまとめています。</p>
<div class="gcards">{cards}</div>
<section class="card"><h2>📉 今日の値下がりピックアップ</h2>
<p class="basis">各ジャンルで直近30日の最高値から{DROP_MIN_PCT:.0f}%以上下がった商品（{updated}更新）。</p>{drop_list}</section>"""
    _write("/", _page(SITE_NAME, home, "楽天市場の暮らしの定番アイテムの価格を毎日記録。値下がり中の商品と評判の良い商品ランキングで買い時が分かります。", "/"))
    pages += 1

    about = f"""
<h1>このサイトについて</h1>
<section class="card">
<h2>買い時ナビとは</h2>
<p>コーヒー・寝具・キッチン用品・ペット用品など、毎日の暮らしで使う定番アイテムの価格を毎日記録し、「今が買い時か」を数字で判断できるようにまとめたサイトです。</p>
<h2>ランキングの根拠</h2>
<ul>
<li>商品データは楽天市場（楽天ウェブサービス）から取得しています。</li>
<li>「値下がり」は、当サイトが毎日記録している価格のうち直近30日の最高値と、更新時点の価格を比べた下落率です。記録日数が少ない商品は対象外です。</li>
<li>「評判の良い」ランキングは、レビュー評価{MIN_AVG}以上・レビュー{MIN_REVIEWS}件以上の商品を、評価の高さとレビュー件数を掛け合わせた点数で並べています。</li>
<li>順位は上記の数値だけで機械的に決めており、広告料などによって順位を上下させることはありません。</li>
</ul>
<h2>広告について</h2>
<p>当サイトのリンクの多くはアフィリエイトリンク（楽天アフィリエイト・A8.net）です。リンク経由で購入・申込があった場合、当サイトに報酬が支払われることがあります。</p>
<h2>運営者</h2>
<p>aki.h190（Instagram・Threadsで「日々のくらしで見つけた、これ良かった」を発信しています）</p>
</section>"""
    _write("/about/", _page("このサイトについて", about, "買い時ナビの運営方針とランキングの根拠", "/about/"))
    privacy = """
<h1>プライバシーポリシー</h1>
<section class="card">
<p>当サイトでは、お問い合わせ等で取得した個人情報を、本人の同意なく第三者に提供することはありません。</p>
<p>当サイトはアフィリエイトプログラム（楽天アフィリエイト・A8.net）を利用しています。リンクのクリックや購入の計測のため、提携先がCookieを使用することがあります。Cookieはブラウザの設定で無効にできます。</p>
<p>当サイトの掲載内容は正確さに努めていますが、価格・在庫等は変動するため、購入前に必ず販売ページでご確認ください。</p>
</section>"""
    _write("/privacy/", _page("プライバシーポリシー", privacy, "買い時ナビのプライバシーポリシー", "/privacy/"))
    pages += 2

    urls = ["/", "/about/", "/privacy/"] + [f"/{g['slug']}/" for g in GENRES] + [
        f"/{g['slug']}/{x['slug']}/" for g in GENRES for x in _guides(g["slug"])]
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               + "".join(f"<url><loc>{SITE_URL}{u}</loc><lastmod>{date.today().isoformat()}</lastmod></url>" for u in urls)
               + "</urlset>\n")
    (OUT_DIR / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (OUT_DIR / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")
    return pages
