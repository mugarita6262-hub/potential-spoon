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
以下の商品それぞれについて、Threads投稿を書いてください。
hookはその商品ジャンルの日常の話題（例: お米なら「お米の値段、みんなどこで買うのが
一番安いと思う？ 最近5kgじゃ全然足りない」）、captionは「ちなみに今見たら楽天でこれが
過去最安だった」のように値下がりを見つけたことを伝えるトーンで。
渡した値引き情報（%OFF や過去最安）はcaptionでだけ触れる。

{split_rules}

# 出力形式（これ以外は何も出力しない。JSON配列のみ）
[{{"itemUrl": "商品URL", "hook": "フック投稿", "caption": "紹介投稿"}}]

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
    return json.loads(text[start : end + 1], strict=False)


def generate_sns_captions(items: list[dict]) -> dict[str, tuple[str, str]]:
    """商品リストから {itemUrl: (フック投稿, 紹介投稿)} を返す（PR表記・リンクは含まない）。"""
    import anthropic

    from .content_captions import SPLIT_RULES

    if not items:
        return {}

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境から取得
    prompt = INSTRUCTION.format(split_rules=SPLIT_RULES) + _item_lines(items)

    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    rows = _extract_json_array(text)

    result: dict[str, tuple[str, str]] = {}
    for row in rows:
        url = (row.get("itemUrl") or "").strip()
        hook = (row.get("hook") or "").strip()
        cap = (row.get("caption") or "").strip()
        if url and hook and cap:
            result[url] = (hook, cap)

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
