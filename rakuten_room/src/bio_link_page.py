"""Instagramのプロフィール欄に置く「リンクインバイオ」ページを生成する。

Instagramはフィード投稿のキャプション内リンクがクリックできないため、
プロフィール欄のリンク1つに現在のおすすめをまとめて置く必要がある。
data/a8_links.yaml の内容をそのままHTML化し、サーバーのCaddyが配信している
ディレクトリ（プライバシーポリシーページと同じサイト）に書き出す。
このモジュールはサーバー上で実行された時だけ実際に書き出す
（ローカル実行時は配信先ディレクトリが無いので静かにスキップする）。
"""
from __future__ import annotations

from pathlib import Path

BIO_PAGE_DIR = Path("/home/kirui/privacy_page/links")

# ジャンルタグ→絵文字（見つからないものは無地のドットにフォールバック）
_GENRE_EMOJI = {
    "飲料・カフェ": "☕",
    "食品・スイーツ": "🍪",
    "美容・スキンケア": "🧴",
    "日用品雑貨": "🧺",
    "キッチン家電": "🍳",
    "ダイエット・健康": "🌿",
    "インテリア・収納": "🛋️",
    "暮らし・家事": "🧺",
    "ペット": "🐶",
}

_HEAD = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>aki.h190 のおすすめ</title>
<style>
:root{
  --cream:#fbf3e7; --card:#ffffff; --ink:#3d2e22; --muted:#9a8874;
  --accent:#c17a4e; --accent-dark:#8b5636; --line:#efe2d2;
}
*{box-sizing:border-box}
body{
  font-family:system-ui,"Hiragino Sans","Yu Gothic UI",sans-serif;
  max-width:480px;margin:0 auto;background:var(--cream);color:var(--ink);
  padding:0 0 40px;
}
.hero{padding:40px 20px 28px;text-align:center}
h1{font-size:17px;margin:0 0 6px}
.sub{font-size:12.5px;color:var(--muted);margin:0;line-height:1.6}
.list{padding:4px 18px}
.card{
  display:flex;align-items:center;gap:12px;
  background:var(--card);border-radius:16px;padding:14px 16px;margin-bottom:12px;
  text-decoration:none;color:var(--ink);
  box-shadow:0 2px 8px rgba(61,46,34,.06);
  border:1px solid var(--line);
  transition:transform .15s ease;
}
.card:active{transform:scale(.98)}
.emoji{font-size:22px;flex:none;width:34px;text-align:center}
.text{flex:1;min-width:0}
.text b{display:block;font-size:13.5px;line-height:1.4;margin-bottom:3px;
        overflow:hidden;text-overflow:ellipsis;display:-webkit-box;
        -webkit-line-clamp:2;-webkit-box-orient:vertical}
.text span{font-size:11.5px;color:var(--muted)}
.arrow{flex:none;color:var(--accent);font-size:18px;opacity:.7}
.empty{text-align:center;color:var(--muted);font-size:13px;padding:20px}
.feature{background:var(--accent);color:#fff;border:0}
.feature .text span{color:#fde9da}
.feature .arrow{color:#fff;opacity:1}
.sec{font-size:12px;font-weight:700;color:var(--accent-dark);margin:18px 4px 8px;letter-spacing:.06em}
.thumb{flex:none;width:56px;height:56px;border-radius:10px;object-fit:cover;background:#f4ece2}
.price{color:var(--accent-dark);font-weight:700}
.pr{text-align:center;font-size:10.5px;color:var(--muted);margin:20px 18px 0;
    padding-top:16px;border-top:1px solid var(--line)}
</style>
</head>
<body>
<div class="hero">
  <h1>aki.h190 のおすすめ</h1>
  <p class="sub">日々のくらしで見つけた「これ良かった」をまとめました</p>
</div>
<div class="list">
"""
_FOOT = ('<p class="pr">紹介している商品にはアフィリエイトリンク（PR）を含みます</p>\n'
         "</div>\n</body></html>\n")


# 自分のサイト（買い時ナビ）への入口。いちばん上に目立つ色で置く
_SITE_CARD = (
    '<a class="card feature" href="https://kaidokinavi.com/?utm_source=bio&amp;utm_medium=social'
    '&amp;utm_campaign=profile" target="_blank" rel="noopener">'
    '<span class="emoji">📉</span>'
    '<span class="text"><b>買い時ナビ｜毎日の価格記録で「買い時」が分かる</b>'
    '<span>お米・水・日用品・洗剤などの値下がりと評判ランキング</span></span>'
    '<span class="arrow">›</span></a>'
)


def _recent_cards(recent: list[dict]) -> list[str]:
    """最近Instagramで紹介した楽天の商品（新しい順）。投稿の「プロフィールのリンクから」の行き先。"""
    out = []
    for it in recent:
        url, name = (it.get("url") or "").strip(), (it.get("name") or "").strip()
        if not url or not name:
            continue
        img = f'<img class="thumb" src="{it["img"]}" alt="" loading="lazy">' if it.get("img") else '<span class="emoji">🛍️</span>'
        price = f'<span class="price">{int(it["price"]):,}円</span>' if it.get("price") else ""
        day = (it.get("posted_at") or "")[5:10].replace("-", "/")
        out.append(
            f'<a class="card" href="{url}" target="_blank" rel="noopener nofollow sponsored">{img}'
            f'<span class="text"><b>{name[:60]}</b><span>{price}{"　" + day + " の投稿" if day else ""}</span></span>'
            f'<span class="arrow">›</span></a>')
    return out


def recent_instagram_items(api, n: int = 12) -> list[dict]:
    """sns_posted.json のInstagram投稿から、まとめページに出す商品情報を作る（アフィリリンク・画像・価格）。
    楽天APIで引いた結果は data/ig_bio_cache.json に残して、毎回引き直さない。"""
    import json
    from .config import DATA_DIR
    from .sns_posted_log import load_posted
    cache_file = DATA_DIR / "ig_bio_cache.json"
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        cache = {}
    posts = [x for x in load_posted() if x.get("platform") == "instagram" and x.get("itemCode")][::-1]
    out, seen = [], set()
    for x in posts:
        code = x["itemCode"]
        if code in seen:
            continue
        seen.add(code)
        if code not in cache:
            try:
                it = api.lookup_by_code(code)
            except Exception:  # noqa: BLE001
                it = None
            cache[code] = ({"name": it["itemName"], "url": it.get("affiliateUrl") or it["itemUrl"],
                            "img": it.get("imageUrl", ""), "price": it.get("price", 0)} if it else {})
        if cache[code]:
            out.append({**cache[code], "posted_at": x.get("posted_at", "")})
        if len(out) >= n:
            break
    cache_file.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return out


def render(items: list[dict], recent: list[dict] | None = None) -> str:
    cards = [_SITE_CARD]
    rc = _recent_cards(recent or [])
    if rc:
        cards.append('<p class="sec">最近Instagramで紹介した商品</p>')
        cards += rc
        cards.append('<p class="sec">おすすめのサービス</p>')
    for it in items:
        name = (it.get("site_name") or it.get("program_name") or it.get("itemName") or "").strip()
        note = (it.get("site_note") or it.get("note") or "").strip()
        url = (it.get("url") or it.get("itemUrl") or "").strip()
        genre = (it.get("genre") or "").strip()
        if not url or not name:
            continue
        emoji = _GENRE_EMOJI.get(genre, "🛍️")
        cards.append(
            f'<a class="card" href="{url}" target="_blank" rel="noopener nofollow sponsored">'
            f'<span class="emoji">{emoji}</span>'
            f'<span class="text"><b>{name[:60]}</b><span>{note[:60]}</span></span>'
            f'<span class="arrow">›</span></a>'
        )
    body = "\n".join(cards) or '<p class="empty">準備中です、もう少しお待ちください</p>'
    return _HEAD + body + _FOOT


def update_bio_page(items: list[dict], recent: list[dict] | None = None) -> bool:
    """更新に成功したらTrue、配信先ディレクトリが無い（＝ローカル実行）場合はFalseを返す。"""
    if not BIO_PAGE_DIR.parent.exists():
        return False
    BIO_PAGE_DIR.mkdir(parents=True, exist_ok=True)
    (BIO_PAGE_DIR / "index.html").write_text(render(items, recent), encoding="utf-8")
    return True
