"""キャプション（紹介文）用のプロンプト書き出しと、生成結果の読み込み。

APIキーを使わない運用:
  1. prepare が data/drafts/<日付>_prompt.md を作る
  2. その中身を丸ごと Claude に貼る
  3. Claude が返した JSON 配列を data/drafts/<日付>_captions.json に保存
  4. post がそれを読み込んでフォームに入力する
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .config import DRAFTS_DIR

PROMPT_HEADER = """\
あなたは楽天ROOMで人気のインフルエンサーです。
以下の商品それぞれについて、楽天ROOMの「コレ！」投稿用の紹介文を書いてください。

# 条件
- 実際に自分で使っている人の口調（敬体、フレンドリー。「〜です・ます」中心、「〜だ・である」禁止）
- 1商品90〜120字
- 具体的な魅力を1〜2点（使用シーン、質感、コスパなど）
- 絵文字は1〜2個まで
- 文末にハッシュタグを3〜5個（#楽天room #楽天roomで購入 など定番＋商品に合ったもの）
- 誇大表現・医薬品的な効能表現は避ける

# 出力形式（これ以外は何も出力しない）
```json
[
  {"itemUrl": "商品URL", "caption": "紹介文＋ハッシュタグ"}
]
```

# 商品リスト
"""


def _today_stem() -> str:
    return date.today().isoformat()


def prompt_path(day: str | None = None) -> Path:
    return DRAFTS_DIR / f"{day or _today_stem()}_prompt.md"


def captions_path(day: str | None = None) -> Path:
    return DRAFTS_DIR / f"{day or _today_stem()}_captions.json"


def drafts_path(day: str | None = None) -> Path:
    return DRAFTS_DIR / f"{day or _today_stem()}_drafts.json"


def write_prompt(items: list[dict]) -> Path:
    lines = [PROMPT_HEADER]
    for i, it in enumerate(items, 1):
        lines.append(
            f"\n{i}. {it['itemName']}\n"
            f"   - URL: {it['itemUrl']}\n"
            f"   - 価格: {it['price']:,}円 / ショップ: {it['shopName']}\n"
            f"   - レビュー: {it['reviewCount']}件 平均{it['reviewAverage']}\n"
            + (f"   - キャッチコピー: {it['caption_hint']}\n" if it.get("caption_hint") else "")
        )
    path = prompt_path()
    path.write_text("".join(lines), encoding="utf-8")
    return path


def save_drafts(items: list[dict]) -> Path:
    path = drafts_path()
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_drafts(day: str | None = None) -> list[dict]:
    path = drafts_path(day)
    if not path.exists():
        raise FileNotFoundError(f"下書きがありません: {path}\n先に `prepare` を実行してください。")
    return json.loads(path.read_text(encoding="utf-8"))


def load_captions(day: str | None = None) -> dict[str, str]:
    path = captions_path(day)
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    # ```json ... ``` で囲まれていても許容
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        raw = raw[4:] if raw.lower().startswith("json") else raw
    data = json.loads(raw)
    return {row["itemUrl"]: row["caption"].strip() for row in data if row.get("itemUrl")}
