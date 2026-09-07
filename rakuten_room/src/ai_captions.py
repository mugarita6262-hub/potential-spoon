"""Claude API で楽天ROOM用のキャプション（紹介文）を自動生成する。

ANTHROPIC_API_KEY が .env にあれば prepare 時に自動で呼ばれる。
bulk 生成なので安価な Haiku 4.5 を使用（1日 数円程度）。
"""
from __future__ import annotations

import json

MODEL = "claude-haiku-4-5"

SYSTEM = """\
あなたは楽天ROOMで人気のインフルエンサー「muga」。
関西在住・3兄弟の母。毎日のごはん・日用品・子育てグッズ・プチプラ美容を中心に、
実際に使ってよかったものを紹介している。スイーツにも目がない。"""

INSTRUCTION = """\
以下の商品それぞれに、楽天ROOMの「コレ！」投稿用の紹介文を書いてください。

# 条件
- 実際に自分で使っている人の口調（敬体・フレンドリー。「〜です・ます」中心、「〜だ・である」禁止）
- 1商品 90〜120字
- 具体的な魅力を1〜2点（使用シーン・質感・コスパ・時短など）
- 絵文字は1〜2個
- 文末にハッシュタグを4〜5個（#楽天room #楽天roomで購入 ＋ 商品に合ったもの）
- 誇大表現・医薬品的な効能表現・ビフォーアフター断定は避ける
- 商品名やキャッチコピーをそのまま貼らず、自分の言葉で

# 出力形式（これ以外は何も出力しない。JSON配列のみ）
[{"itemUrl": "商品URL", "caption": "紹介文＋ハッシュタグ"}]

# 商品リスト
"""


def _item_lines(items: list[dict]) -> str:
    out = []
    for i, it in enumerate(items, 1):
        out.append(
            f"{i}. {it['itemName'][:110]}\n"
            f"   URL: {it['itemUrl']}\n"
            f"   価格: {it['price']:,}円 / ショップ: {it['shopName']} / "
            f"レビュー{it['reviewCount']}件 平均{it['reviewAverage']}\n"
            + (f"   キャッチコピー: {it['caption_hint'][:100]}\n" if it.get("caption_hint") else "")
        )
    return "\n".join(out)


def _extract_json_array(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("JSON配列が見つかりませんでした")
    return json.loads(text[start : end + 1])


def generate_captions(items: list[dict]) -> dict[str, str]:
    """商品リストからキャプションを生成。{itemUrl: caption} を返す。"""
    import anthropic

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境から取得
    prompt = INSTRUCTION + _item_lines(items)

    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    rows = _extract_json_array(text)

    result: dict[str, str] = {}
    for row in rows:
        url = (row.get("itemUrl") or "").strip()
        cap = (row.get("caption") or "").strip()
        if url and cap:
            result[url] = cap

    usage = resp.usage
    cost = usage.input_tokens * 1e-6 + usage.output_tokens * 5e-6
    print(f"  キャプション生成: {len(result)}件 / "
          f"入力{usage.input_tokens}・出力{usage.output_tokens}トークン（約${cost:.4f}）")
    return result
