"""Claude API で Threads 投稿用の短い告知文（値下がり・セール検知）を生成する。

ROOM向けの ai_captions.py とは狙いが違う：
「値下がり・セールを見つけて教える」トーンの短文。ハッシュタグ・PR表記・リンクは
AIには出させず、build_post_text() でコード側が必ず付与する（ステマ規制対応）。
"""
from __future__ import annotations

import json

MODEL = "claude-haiku-4-5"

SYSTEM = """\
あなたは楽天ROOMで人気のインフルエンサー「muga」。
関西在住・3兄弟の母。値下がり・セール情報をいち早く見つけて教えてくれる人、という設定で
Threadsに短い告知投稿を書く。"""

INSTRUCTION = """\
以下の商品それぞれについて、Threads投稿用の短い告知文を書いてください。
「値下がりしているのを見つけたので教える」トーンで。

# 構成（最重要）
**1文目は「フック」にする。** 商品名からいきなり入らず、パッと目に入る短くカジュアルな
一文から始める。例えば：
  - 具体的な驚き（「え、これそんなに下がってるの？って二度見した」）
  - あるある・共感（「セール待ってた人、今がチャンスです」）
  - 価格に触れる前のワンクッション（渡した値引き情報は2文目以降で自然に）
フック文は敬体を保ちつつ、「え」「まって」「地味に」「正直」のような口語的な
相槌・言い切りを使ってOK。堅苦しくならず、思わずつぶやいたような自然さを優先する。
**フック文の直後に空行を1つ入れて**、2文目以降（本文）と視覚的に分ける
（captionの文字列の中に改行を2つ＝空行として含めること）。
「【PR】」から書き始めるのは禁止（フックにならないため）。

# 条件
- 敬体・フレンドリー（「〜です・ます」中心、「〜だ・である」禁止）
- 1商品 80〜140字（フック文＋本文＋問いかけ）
- 渡した値引き情報（%OFF や過去最安）は2文目以降で自然に触れる
- 絵文字は1個まで
- ハッシュタグ・PR表記は付けない（システム側で末尾に付与するため）
- 誇大表現・煽り文句・医薬品的な効能表現は避ける
- 商品名やキャッチコピーをそのまま貼らず、自分の言葉で
- **AI臭さを避ける**: 「〜なのが嬉しいポイントです」のような紋切り型の褒め方、
  毎回同じ書き出し、やたら整った文章構成にしない。
  友達にふと話すときのような、多少くだけた・言い切らない言い回しでOK
- 全部の投稿で似た構成・似たフックにならないよう、パターンを毎回変える
- **最後は必ず「思わず返信したくなる問いかけ」で締める**（Threadsはいいね数より
  リプライ数・会話の深さが伸びを左右するため。YES/NOで即答できる軽いものでOK）

# 出力形式（これ以外は何も出力しない。JSON配列のみ）
[{"itemUrl": "商品URL", "caption": "フック文から始まる告知文（ハッシュタグ・リンクなし）"}]

# 商品リスト
"""


def _item_lines(items: list[dict]) -> str:
    out = []
    for i, it in enumerate(items, 1):
        tag = "過去最安値" if it.get("is_all_time_low") else f"約{it.get('drop_pct', 0):.0f}%OFF"
        out.append(
            f"{i}. {it['itemName'][:100]}\n"
            f"   URL: {it['itemUrl']}\n"
            f"   現在価格: {it['price']:,}円（{tag} / 直近参考価格 "
            f"{it.get('reference_price', it['price']):,}円）\n"
            f"   ショップ: {it['shopName']}\n"
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


def generate_sns_captions(items: list[dict]) -> dict[str, str]:
    """商品リストから告知文を生成。{itemUrl: caption} を返す（PR表記・リンクは含まない）。"""
    import anthropic

    if not items:
        return {}

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境から取得
    prompt = INSTRUCTION + _item_lines(items)

    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
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
    print(f"  Threads告知文生成: {len(result)}件 / "
          f"入力{usage.input_tokens}・出力{usage.output_tokens}トークン（約${cost:.4f}）")
    return result


def build_post_text(item: dict, caption: str, disclosure: str = "PR") -> str:
    """AI生成の告知文（フックから始まる）をそのまま先頭に置き、リンク・ハッシュタグは
    末尾にまとめる。PR表記は必ずハッシュタグの先頭（#PR）としてコード側で固定で付ける
    （AI任せにしない。景品表示法のステマ規制対応。詳細は a8_captions.build_post_text 参照）。
    """
    link = item.get("affiliateUrl") or item.get("itemUrl", "")
    tags = f"#{disclosure} #楽天room #楽天セール"
    return f"{caption}\n\n{link}\n{tags}".strip()
