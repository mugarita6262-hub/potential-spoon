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
- おすすめを紹介する人の口調（敬体、フレンドリー。「〜です・ます」中心、「〜だ・である」禁止）
- 使ったふりをしない。実際に使った・買ったと読める体験談（「使ってみて」「愛用中」「うちの子が毎日」
  「〜が改善された」「リピートしてます」など）は書かない。家族や生活の具体的なエピソードも作らない
- 魅力は、レビュー評価・件数・価格・仕様・商品説明から分かる事実をもとに、紹介者として書く
  （「レビュー◯件で評価が高い」「この容量でこの価格」「〜な人に向いていそう」「気になっている」など）
- 体の形・成長・発達・姿勢への効果（頭の形が整う・絶壁防止・姿勢が良くなる・体幹が鍛えられる・背が伸びる等）も書かない
- 1商品90〜120字
- 具体的な魅力を1〜2点（使用シーン、質感、コスパなど）
- 絵文字は1〜2個まで
- 文末にハッシュタグを3〜5個（#楽天room ＋ 商品に合ったもの。#楽天roomで購入 など購入したと読めるタグは付けない）
- 誇大表現・医薬品的な効能表現は避ける
- 体や肌への効果・変化（「スッキリした」「よく眠れた」「調子がいい」「肌が変わった」など）や、
  効果を感じたような体験談は書かない。使い心地は香り・手ざわり・使い勝手・見た目の範囲にとどめる

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


def plan_path(day: str | None = None) -> Path:
    return DRAFTS_DIR / f"{day or _today_stem()}_plan.json"


def save_plan(plan: dict, day: str | None = None) -> Path:
    p = plan_path(day)
    p.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_plan(day: str | None = None) -> dict:
    p = plan_path(day)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


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
