"""Kindle電子書籍の企画アイデアを生成する。"""
from __future__ import annotations

import json

MODEL = "claude-opus-5"

SYSTEM = """\
あなたは日本のKindle出版（KDP）に詳しい企画編集者です。
Kindle Unlimitedでの読了・購入につながる、実用的なノウハウ本の企画を考えます。
- 規制業種（医療・法律・投資助言など、資格が必要な断定的アドバイス）は避ける
- 生成AIを執筆に使うことをAmazonに申告する前提（申告済みでも売れる企画にする）
- competitive だが検索されやすいニッチ（ロングテールキーワード）を狙う
- 1冊は 15,000〜30,000字程度（電子書籍として自然な分量）を想定
"""

PROMPT_TMPL = """\
以下の条件で、Kindle電子書籍の企画を{n}件、JSON配列で出してください。

条件:
{theme_line}
- 各企画は独立したテーマ（ジャンルが偏らないよう分散させる）
- 出力はJSON配列のみ。説明文やコードフェンスは不要

各要素の形式:
{{
  "title": "書名（32文字程度、検索されやすいキーワードを含む）",
  "subtitle": "サブタイトル（具体的なベネフィット）",
  "reader": "想定読者（1文）",
  "hook": "この本ならではの切り口・差別化ポイント（1〜2文）",
  "chapters": ["第1章の見出し", "第2章の見出し", "...", "第6章くらいまで"],
  "keywords": ["Amazon内検索で使われそうなキーワード", "..."],
  "price_yen": 300,
  "est_chars": 20000
}}
"""


def _extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    return json.loads(text[start:end + 1])


def generate_ideas(theme_hint: str = "", n: int = 8) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic()
    theme_line = (f"- テーマの方向性: {theme_hint}" if theme_hint.strip()
                  else "- テーマは自由（家事・節約・仕事術・人間関係・子育て・趣味など実用系で幅広く）")
    prompt = PROMPT_TMPL.format(n=n, theme_line=theme_line)

    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    ideas = _extract_json(text)

    usage = resp.usage
    cost = usage.input_tokens * 5e-6 + usage.output_tokens * 25e-6
    print(f"  （生成: 入力{usage.input_tokens}・出力{usage.output_tokens}トークン、約${cost:.3f}）")
    return ideas


def print_ideas(ideas: list[dict]) -> None:
    for i, idea in enumerate(ideas, 1):
        print(f"\n{'=' * 60}\n【{i}】{idea.get('title', '')}")
        print(f"    {idea.get('subtitle', '')}")
        print(f"  読者: {idea.get('reader', '')}")
        print(f"  切り口: {idea.get('hook', '')}")
        print(f"  価格目安: {idea.get('price_yen', '?')}円 / 想定{idea.get('est_chars', '?')}字")
        print("  章立て:")
        for c in idea.get("chapters", []):
            print(f"    - {c}")
        print(f"  キーワード: {', '.join(idea.get('keywords', []))}")
