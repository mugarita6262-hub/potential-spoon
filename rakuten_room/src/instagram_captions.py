"""Claude API で Instagram投稿用のキャプションを生成する。

Threads向け（a8_captions.py等）とほぼ同じフック優先の方針だが、Instagramは
キャプション内のリンクがクリックできない（プロフィール欄のリンク1つだけがクリック可）
という制約があるため、「プロフィールのリンクから見てね」という誘導を必ず入れる。
"""
from __future__ import annotations

import json

MODEL = "claude-haiku-4-5"

SYSTEM = """\
あなたは日々の暮らしで見つけた「これ良かった」を紹介するInstagram運用者。
コーヒー・お茶・キッチン家電など、普段の生活を少し豊かにするアイテムが好き。"""

INSTRUCTION = """\
以下の商品について、Instagram投稿用の短いキャプションを書いてください。
「実際に気に入って使っている・気になっている」という自然なトーンで。

# 構成（最重要）
1文目は「フック」にする。商品名からいきなり入らず、パッと目に入る短くカジュアルな
一文から始める。フック文の直後に空行を1つ入れて、2文目以降の本文と視覚的に分ける
（captionの文字列内に改行を2つ含めること）。フックは敬体を保ちつつ「え」「まって」
「地味に」のような口語的な相槌もOK。

# 条件
- 敬体・フレンドリー（「〜です・ます」中心）
- 全体で80〜140字（フック文＋本文＋問いかけ）
- 具体的な魅力を1点だけ
- 絵文字は1個まで
- ハッシュタグ・PR表記・「プロフィールのリンクから」の案内は付けない（システム側で末尾に付与）
- 誇大表現・医薬品的な効能表現は避ける
- 商品名をそのまま貼らず、自分の言葉で
- AI臭い紋切り型の褒め方は避け、友達にふと話すような自然な言い回しにする
- 最後は必ず「思わず返信したくなる問いかけ」で締める

# 出力形式（これ以外は何も出力しない。JSON配列のみ）
[{"caption": "フック文から始まるキャプション"}]

# 商品情報
"""


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
    return json.loads(text[start : end + 1], strict=False)


def generate_instagram_caption(item: dict) -> str:
    """商品1件からキャプションを生成して返す（ハッシュタグ・PR表記・リンク案内なし）。"""
    import anthropic

    client = anthropic.Anthropic()
    lines = (
        f"商品名: {item['itemName'][:100]}\n"
        f"価格: {item['price']:,}円 / ショップ: {item.get('shopName', '')}\n"
        f"レビュー: {item.get('reviewCount', 0)}件 平均{item.get('reviewAverage', 0)}\n"
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=SYSTEM,
        messages=[{"role": "user", "content": INSTRUCTION + lines}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    rows = _extract_json_array(text)
    usage = resp.usage
    cost = usage.input_tokens * 1e-6 + usage.output_tokens * 5e-6
    print(f"  Instagramキャプション生成: 入力{usage.input_tokens}・出力{usage.output_tokens}"
          f"トークン（約${cost:.4f}）")
    return (rows[0].get("caption") or "").strip() if rows else ""


def build_instagram_post_text(caption: str, disclosure: str = "PR") -> str:
    """キャプションに、プロフィールリンクへの誘導・ハッシュタグ・PR表記を付与する。

    Instagramはキャプション内のリンクがクリックできないため、プロフィール欄の
    リンク（bio link）に誘導する文言を必ず入れる。PR表記は末尾ハッシュタグの
    先頭に固定で付ける（AI任せにしない。景品表示法のステマ規制対応）。
    """
    tags = f"#{disclosure} #暮らしを豊かに #楽天room"
    return f"{caption}\n\n気になった人はプロフィールのリンクからチェックしてみてください🔗\n\n{tags}".strip()
