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

# 条件
- 敬体・フレンドリー（「〜です・ます」中心、「〜だ・である」禁止）
- 1商品 60〜100字
- 渡した値引き情報（%OFF や過去最安）はそのまま自然に触れてよい
- 絵文字は1個まで
- ハッシュタグは付けない（システム側で付与するため）
- 誇大表現・煽り文句・医薬品的な効能表現は避ける
- 商品名やキャッチコピーをそのまま貼らず、自分の言葉で

# 出力形式（これ以外は何も出力しない。JSON配列のみ）
[{"itemUrl": "商品URL", "caption": "告知文（ハッシュタグ・リンクなし）"}]

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


def build_post_text(item: dict, caption: str, disclosure: str = "【PR】") -> str:
    """AI生成の告知文に、PR表記・アフィリリンク・定番ハッシュタグを付与した最終投稿文を組み立てる。

    ステマ規制（景品表示法）対応のため、PR表記は必ずここ（コード側）で先頭に固定で付ける。
    AIの出力任せにしない。
    """
    link = item.get("affiliateUrl") or item.get("itemUrl", "")
    tags = "#楽天room #楽天セール #タイムセール"
    return f"{disclosure} {caption}\n{link}\n{tags}".strip()
