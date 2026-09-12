"""Claude API で A8アフィリリンク用のThreads紹介文を生成する。

sns_captions.py（値下がり告知）とは別で、こちらは「使ってみて良かった商品を
紹介する」トーンの通常の商品紹介文。ハッシュタグ・PR表記・リンクはコード側で
付与する（sns_captions.build_post_text と同じ方針）。
"""
from __future__ import annotations

import json

MODEL = "claude-haiku-4-5"

SYSTEM = """\
あなたは日々の暮らしで見つけた「これ良かった」を紹介するInstagram/Threads運用者。
コーヒー・お茶・キッチン家電など、普段の生活を少し豊かにするアイテムが好き。"""

INSTRUCTION = """\
以下の商品・サービスそれぞれについて、Threads投稿用の短い紹介文を書いてください。
「実際に気に入って使っている・気になっている」という自然なトーンで。

# 条件
- 敬体・フレンドリー（「〜です・ます」中心、「〜だ・である」禁止）
- 1件 60〜100字
- 具体的な魅力を1点だけ（味・香り・時短・手軽さなど。渡した情報から想像できる範囲で）
- 絵文字は1個まで
- ハッシュタグは付けない（システム側で付与するため）
- 誇大表現・医薬品的な効能表現・断定的な効果の保証は避ける
- 商品名をそのまま貼らず、自分の言葉で

# 出力形式（これ以外は何も出力しない。JSON配列のみ）
[{"program_id": "プログラムID", "caption": "紹介文（ハッシュタグ・リンクなし）"}]

# 商品・サービス一覧
"""


def _item_lines(items: list[dict]) -> str:
    out = []
    for i, it in enumerate(items, 1):
        out.append(
            f"{i}. program_id: {it['program_id']}\n"
            f"   商品・サービス名: {it['program_name'][:100]}\n"
            f"   紹介ページ: {it.get('note', '')}\n"
            f"   提供元: {it.get('advertiser', '')}\n"
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


def generate_a8_captions(items: list[dict]) -> dict[str, str]:
    """商品リストから紹介文を生成。{program_id: caption} を返す（PR表記・リンクは含まない）。"""
    import anthropic

    if not items:
        return {}

    client = anthropic.Anthropic()
    prompt = INSTRUCTION + _item_lines(items)

    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    rows = _extract_json_array(text)

    result: dict[str, str] = {}
    for row in rows:
        pid = (row.get("program_id") or "").strip()
        cap = (row.get("caption") or "").strip()
        if pid and cap:
            result[pid] = cap

    usage = resp.usage
    cost = usage.input_tokens * 1e-6 + usage.output_tokens * 5e-6
    print(f"  A8紹介文生成: {len(result)}件 / "
          f"入力{usage.input_tokens}・出力{usage.output_tokens}トークン（約${cost:.4f}）")
    return result


def build_post_text(item: dict, caption: str, disclosure: str = "【PR】") -> str:
    """AI生成の紹介文に、PR表記・アフィリリンク・定番ハッシュタグを付与した最終投稿文を組み立てる。

    ステマ規制（景品表示法）対応のため、PR表記は必ずここ（コード側）で先頭に固定で付ける。
    """
    tags = "#PR #暮らしを豊かに"
    return f"{disclosure} {caption}\n{item['url']}\n{tags}".strip()
