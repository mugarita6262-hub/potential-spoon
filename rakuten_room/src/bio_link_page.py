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

_HEAD = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>おすすめリンク</title>
<style>
body{font-family:system-ui,"Yu Gothic UI",sans-serif;max-width:480px;margin:0 auto;
     padding:24px 16px;background:#fafafa;color:#222}
h1{font-size:18px;text-align:center}
.card{display:block;background:#fff;border-radius:12px;padding:16px;margin-bottom:12px;
      text-decoration:none;color:#222;box-shadow:0 1px 3px rgba(0,0,0,.1)}
.card b{display:block;font-size:14px;margin-bottom:4px}
.card span{font-size:12px;color:#888}
.pr{text-align:center;font-size:11px;color:#aaa;margin-top:8px}
</style>
</head>
<body>
<h1>今のおすすめ</h1>
"""
_FOOT = '<p class="pr">アフィリエイトリンクを含みます（PR）</p>\n</body></html>\n'


def render(items: list[dict]) -> str:
    cards = []
    for it in items:
        name = (it.get("program_name") or it.get("itemName") or "").strip()
        note = (it.get("note") or "").strip()
        url = (it.get("url") or it.get("itemUrl") or "").strip()
        if not url or not name:
            continue
        cards.append(
            f'<a class="card" href="{url}" target="_blank" rel="noopener nofollow sponsored">'
            f'<b>{name[:60]}</b><span>{note[:60]}</span></a>'
        )
    body = "\n".join(cards) or '<p style="text-align:center;color:#888">準備中です</p>'
    return _HEAD + body + _FOOT


def update_bio_page(items: list[dict]) -> bool:
    """更新に成功したらTrue、配信先ディレクトリが無い（＝ローカル実行）場合はFalseを返す。"""
    if not BIO_PAGE_DIR.parent.exists():
        return False
    BIO_PAGE_DIR.mkdir(parents=True, exist_ok=True)
    (BIO_PAGE_DIR / "index.html").write_text(render(items), encoding="utf-8")
    return True
