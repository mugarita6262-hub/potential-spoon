"""投稿数を増やすための「条件に依存しない」コンテンツ生成。

sns/a8は「値下がりが見つかった時だけ」「A8リンクがある時だけ」しか投稿できず
出現頻度が低い。こちらはジャンル単位の情報発信で、ほぼ毎回投稿できるネタ。
- digest: ジャンル別の売れ筋ダイジェスト（リンクあり・PRあり）
- trend : ジャンルの価格トレンド速報（リンクなし・PR不要の情報発信）
- calendar: セール・お得日のお知らせ（リンクなし・PR不要の情報発信）
"""
from __future__ import annotations

import json

MODEL = "claude-haiku-4-5"

SYSTEM = """\
あなたは楽天の売れ筋・お得情報を追いかけているThreads運用者。
データに基づいた気づきを、押し付けがましくなく短くシェアするのが得意。"""


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


def _call(instruction: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=SYSTEM,
        messages=[{"role": "user", "content": instruction}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    rows = _extract_json_array(text)
    usage = resp.usage
    cost = usage.input_tokens * 1e-6 + usage.output_tokens * 5e-6
    print(f"  告知文生成: 入力{usage.input_tokens}・出力{usage.output_tokens}トークン"
          f"（約${cost:.4f}）")
    caption = (rows[0].get("caption") or "").strip() if rows else ""
    return caption


HOOK_RULES = """\
# 構成（最重要）
1文目は「フック」にする。パッと目に入る短くカジュアルな一文から始め、
フック文の直後に空行を1つ入れて（captionの文字列内に改行を2つ）、2文目以降の
本文と視覚的に分ける。フックは敬体を保ちつつ「え」「まって」「地味に」のような
口語的な相槌もOK。

# 条件
- 敬体・フレンドリー（「〜です・ます」中心）
- 全体で80〜140字（フック文＋本文＋問いかけ）
- 絵文字は1個まで
- ハッシュタグは付けない（システム側で付与）
- AI臭い紋切り型の褒め方（「〜なのが嬉しいポイントです」等）は避け、
  友達にふと話すような自然な言い回しにする
- **最後は必ず「思わず返信したくなる問いかけ」で締める**（Threadsはいいね数より
  リプライ数・会話の深さが伸びを左右するため。YES/NOで即答できる軽いものでOK。
  例:「みんなはどっち派？」「これ知ってた？」「試したことある人いる？」）
- 出力はこれ以外何も含めないJSON配列のみ: [{"caption": "本文"}]
"""


def generate_digest_caption(genre_name: str, items: list[dict]) -> str:
    """ジャンル売れ筋トップ3の紹介文（リンクあり想定なのでPRは呼び出し側で付与）。"""
    lines = []
    for i, it in enumerate(items[:3], 1):
        lines.append(f"{i}位: {it['itemName'][:60]}（{it['price']:,}円、"
                      f"レビュー{it['reviewCount']}件 平均{it['reviewAverage']}）")
    instruction = f"""\
楽天市場の「{genre_name}」ジャンルの現在の売れ筋ランキングです。
これを見て気づいたこと・意外だったことを含めて、Threads投稿用の紹介文を書いてください。

{HOOK_RULES}

# ランキング情報
{chr(10).join(lines)}
"""
    return _call(instruction)


def generate_trend_caption(genre_name: str, pct_change: float, direction: str) -> str:
    """ジャンルの価格トレンド速報（リンクなし・PR不要の情報発信）。"""
    instruction = f"""\
楽天市場の「{genre_name}」ジャンルで、直近1週間の平均価格が
{abs(pct_change):.0f}%{direction}という変化がありました。
これをThreads投稿でシェアする短い文章を書いてください。値下がりなら
「買い時かも」というニュアンス、値上がりなら「今のうちに」というニュアンスでOK。
特定の商品名やリンクには触れない（ジャンル全体の話として）。

{HOOK_RULES}
"""
    return _call(instruction)


def generate_calendar_caption(event_name: str, hint: str) -> str:
    """セール・お得日のリマインド投稿（リンクなし・PR不要の情報発信）。"""
    instruction = f"""\
楽天市場で「{event_name}」（{hint}）というタイミングが近づいています。
これをThreads投稿でシェアする短いリマインド文を書いてください。
特定の商品名やリンクには触れない（日付・イベントの話として）。

{HOOK_RULES}
"""
    return _call(instruction)


def generate_trivia_caption(topic: str) -> str:
    """ミニ知識・あるあるネタ（リンクなし・PR不要の情報発信）。

    値下がり・A8リンクなど外部データに一切依存しないので、一番身軽に投稿できるネタ。
    """
    instruction = f"""\
「{topic}」にまつわる、ちょっとした豆知識か「あるある」を1つ、Threads投稿として
シェアしてください。誇張せず、へえと思えるくらいの軽い内容でOK。
特定の商品名やブランド名、リンクには触れない（雑学・共感ネタとして）。
最後に「みんなはどう？」のような軽い問いかけを1つ添えると、コメントが来やすい。

{HOOK_RULES}
"""
    return _call(instruction)


def generate_reply_drafts(target_post_text: str, n: int = 3) -> list[str]:
    """他アカウントの投稿へのリプライ下書きを複数案作る（貼り付け・投稿は人がやる）。

    Threads公式APIには他人の投稿を検索・発見する機能が無いため自動化できない。
    「良さそうな投稿を見つける」のは人の仕事、「気の利いた返信を考える」のを
    ここで肩代わりする、という役割分担。リプライ数はThreadsの伸びに直結する
    （いいね数より重視される）ため、質の高いリプライを増やす助けになる。
    """
    import anthropic

    if not target_post_text.strip():
        return []

    client = anthropic.Anthropic()
    instruction = f"""\
以下はThreadsで見つけた、あなたが返信しようとしている他アカウントの投稿です。

---
{target_post_text.strip()[:500]}
---

この投稿に対する自然なリプライ文を{n}パターン考えてください。

# 条件
- 敬体・フレンドリー、1件30〜80字
- それ単体で意味の通る、内容のあるコメントにする（「いいですね！」のような
  中身のない相槌はNG。相手の投稿の具体的な部分に触れる）
- 自分の宣伝・リンクは一切含めない（純粋な会話としてのリプライ）
- 絵文字は0〜1個
- {n}パターンはそれぞれ違う角度で（共感・質問・軽い体験談など）

# 出力形式（これ以外は何も出力しない。JSON配列のみ）
[{{"reply": "リプライ文1"}}, {{"reply": "リプライ文2"}}, ...]
"""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=SYSTEM,
        messages=[{"role": "user", "content": instruction}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    rows = _extract_json_array(text)
    usage = resp.usage
    cost = usage.input_tokens * 1e-6 + usage.output_tokens * 5e-6
    print(f"  リプライ下書き生成: {len(rows)}件 / "
          f"入力{usage.input_tokens}・出力{usage.output_tokens}トークン（約${cost:.4f}）")
    return [r.get("reply", "").strip() for r in rows if r.get("reply")]


def build_digest_post_text(item: dict, caption: str, disclosure: str = "PR") -> str:
    """digest用: リンクありなのでPR表記あり。"""
    link = item.get("affiliateUrl") or item.get("itemUrl", "")
    tags = f"#{disclosure} #楽天ランキング"
    return f"{caption}\n\n{link}\n{tags}".strip()


def build_info_post_text(caption: str, tags: str = "#楽天セール情報") -> str:
    """trend/calendar用: リンクなしなのでPR表記なし。"""
    return f"{caption}\n\n{tags}".strip()
