"""Threads 投稿の文章を Claude Haiku で作る。
- dealdrop: 買い時ナビの値下がり速報（フック＋PR付き引用。cmd_sitedrop）
- calendar: セール・お得日のお知らせ（リンクなし）
- trivia  : 買い物の比べ方の豆知識（リンクなし）
"""
from __future__ import annotations

import json
import re

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
    return json.loads(text[start : end + 1], strict=False)


def today_note() -> str:
    """AIは今日の日付を知らないので、季節外れの話題（10月に「春の模様替え」等）を書く。
    投稿文生成のプロンプトには必ずこれを付ける。"""
    from datetime import date

    d = date.today()
    season = {12: "冬", 1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春",
              6: "夏", 7: "夏", 8: "夏", 9: "秋", 10: "秋", 11: "秋"}[d.month]
    note = (f"# 今日の日付\n{d.year}年{d.month}月{d.day}日（季節は{season}）。"
            "季節やイベントに触れるときは、この時期に合ったものだけにすること。"
            "ただし季節の話は毎回入れなくてよい（入れすぎると同じような投稿が続く）。\n\n")
    from .recent_openings import recent

    openings = recent()
    if openings:
        note += ("# 直近の自分の投稿の書き出し（これと被らないようにする）\n"
                 + "".join(f"- {o}\n" for o in openings)
                 + "上と同じ・似た書き出し（「秋になると」「〇〇って、〜ですよね」など同じ型）や、"
                   "同じ季節ネタ・同じ言い回しは使わない。書き出しの型を毎回変えること。\n\n")
    return note


def _call(instruction: str) -> str:
    rows = _call_rows(instruction)
    return (rows[0].get("caption") or "").strip() if rows else ""


def _call_rows(instruction: str) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=SYSTEM,
        messages=[{"role": "user", "content": today_note() + instruction}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    rows = _extract_json_array(text)
    usage = resp.usage
    cost = usage.input_tokens * 1e-6 + usage.output_tokens * 5e-6
    print(f"  告知文生成: 入力{usage.input_tokens}・出力{usage.output_tokens}トークン"
          f"（約${cost:.4f}）")
    return rows


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


DEAL_RULES = """# このアカウントについて（最重要）
楽天の価格を毎日記録して、値下がりを見つけたら知らせる「値下がり情報アカウント」。
フォローしておけば欲しいものが安くなったときに気づける、という価値で読まれる。
- **使ったふり・家族やペットの体験談は書かない**（「うちの子」「子どもが」「愛用中」「使ってみて」など禁止）。
  書き手は「毎日価格を見ている人」としてだけ話す
- 健康・美容・体への効果はうたわない。誇大表現・断定（「絶対」「今しかない」）もしない

## hook（PRもリンクも付かない単体の投稿）
- **ペルソナに直接呼びかける**: その人が「ちょうど買おうと思ってた」と感じるタイミングの一言から始める
  呼びかけは「〜な人」「〜してる人」への二人称。**書き手自身の生活（家族・子ども・ペット・自分の家・朝ごはんの支度など）は書かない**
  （例:「ストック、そろそろ切れそうな人へ」「寒くなってきて〇〇を探してる人」）
- 渡した**ジャンル全体の数字（値下がり件数・最大の下げ幅）をそのまま**入れる。数字を変えない・足さない
- **商品名・ブランド名・ショップ名は出さない**（ジャンル全体の話にとどめる）
- 「このあと」「下に」「リプ欄」など続きを匂わせる言葉は使わない（引用への案内とPRはシステムが末尾に付ける）
- 「30日」「1か月」など記録期間を書かない（商品ごとに記録日数が違うため）
- 1文目の直後に空行（文字列内に改行2つ）。70〜120字、敬体でフレンドリー、絵文字は1個まで
- 最後は軽い問いかけ（「買い足し予定ある人いる？」など）

## caption（hookを引用する紹介投稿。#PR・リンク・商品の一覧はシステムが付ける）
- 1〜2文、40〜80字。hookの続きとして「特に下がってたのはこのあたりです」のように一覧へつなぐ。
  一覧には商品名と下げ幅だけが載り、いまの値段と値動きはリンク先で見られる（その前提で書く）
- 商品名・数字は書かない（一覧をシステムが正確に付けるため）
"""


def generate_dealdrop_caption(genre_name: str, persona: str, n_drops: int, max_pct: float,
                              n_low: int, slot: str) -> tuple[str, str]:
    """値下がり速報（ペルソナ・時間帯向け）の (hook, caption)。数字が違えば作り直す。"""
    when = {"morning": "朝（出かける前・朝ごはんの時間）", "noon": "昼（お昼休み・家事の合間）",
            "night": "夜（くつろいでスマホを見る時間）"}[slot]
    who = persona.removesuffix("に") if persona else f"{genre_name}を買う予定の人"
    instruction = f"""いま{when}に投稿します。
- ジャンル: {genre_name}
- 呼びかける相手（ペルソナ）: {who}
- ジャンル全体で、ふだんの価格（記録した価格の中央値）より5%以上安くなっている商品: {n_drops}件
- ジャンル全体でいちばん大きい下げ幅: {max_pct:.0f}%
- 記録上の最安値になっている商品: {n_low}件（0件なら触れない）
- 件数はジャンル全体の数。ペルソナ向けの件数のようには書かない（「〇〇な人向けが{n_drops}件」は誤り）

{DEAL_RULES}

# 出力形式（これ以外は何も出力しない。JSON配列のみ）
[{{"hook": "フック投稿", "caption": "紹介投稿"}}]
"""
    for _ in range(2):
        rows = _call_rows(instruction)
        if not rows:
            continue
        hook = (rows[0].get("hook") or "").strip()
        cap = (rows[0].get("caption") or "").strip()
        if f"{n_drops}" in hook and f"{max_pct:.0f}" in hook and not re.search(r"うちの|うちは|我が家|家族の分|子ども|愛用|使ってみ|今がチャンス|今しかない|絶対", hook + cap):
            return hook, cap
        print("  数字・表現の条件を満たさないので作り直します: " + hook[:60])
    return "", ""


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
書き手は「楽天の価格を毎日記録している人」。使ったふり・家族やペットの体験談は書かない。
楽天の具体的なポイント倍率・キャンペーン条件は書かない（変わるため。一般的なコツにとどめる）。
具体的な価格・割引率・「何月が何%安い」のような数字は書かない（裏付けのない数字になるため）。
業界の事情・値下がりする時期とその理由・メーカーの動きなど、確かめようのない事実は書かない。比べ方・考え方のコツ（単価で比べる、送料込みで比べる等）にとどめる。

{HOOK_RULES}
"""
    return _call(instruction)


def build_info_post_text(caption: str, tags: str = "#楽天セール情報") -> str:
    """trend/calendar用: リンクなしなのでPR表記なし。"""
    return f"{caption}\n\n{tags}".strip()
