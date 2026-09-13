"""insightsの結果から、次のアクションを自動で判定する。

「調査結果を自分で解釈して判断する」手間を無くすための層。
- 楽天ジャンル: 反応が良い調査専用ジャンルがあれば、config.yamlを書き換えて
  投稿候補ジャンルに自動で昇格させる（人の判断を待たない）
- A8: 反応が良いジャンルがあれば、自動申請はできないので代わりに
  docs/A8アフィリリンク取得依頼.md に「次はこのジャンルを探してください」という
  依頼を自動で追記する（人・コワーカーは追記された指示に従うだけでいい）
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import yaml

from .config import DATA_DIR, ROOT
from .notify import notify

CONFIG_PATH = ROOT / "config.yaml"
A8_REQUEST_DOC = ROOT / "docs" / "A8アフィリリンク取得依頼.md"
STATE_FILE = DATA_DIR / "optimizer_state.json"

MIN_SAMPLE_RAKUTEN = 3     # これ未満の投稿件数では判断しない（ブレを避ける）
MIN_SAMPLE_A8 = 1          # A8はプログラム自体が少ないので緩め
GOOD_MULTIPLIER = 1.3      # 全体平均のこの倍以上を「好調」とみなす
RESUGGEST_AFTER_DAYS = 14  # 同じジャンルを再提案するまでの間隔


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _save_config(cfg: dict) -> None:
    header = (
        "# 楽天ROOM 投稿ツール 設定\n"
        "# 主な項目は GUI の『⚙ 設定』から変更できます（このファイルを直接編集する必要はありません）\n"
        "# scoring / per_genre / favorites などの詳細はここで調整します\n\n"
    )
    CONFIG_PATH.write_text(
        header + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False,
                                 default_flow_style=False),
        encoding="utf-8",
    )


def _baseline_avg_likes(rows: list[dict], min_sample: int) -> float:
    eligible = [r for r in rows if r["count"] >= min_sample]
    if not eligible:
        return 0.0
    return sum(r["avg_likes"] for r in eligible) / len(eligible)


def auto_promote_rakuten_genres(rows: list[dict]) -> list[str]:
    """調査専用ジャンル(research.extra_genre_ids)のうち反応が良いものを、
    投稿候補ジャンル(sources.ranking.genre_ids)に自動で昇格させる。
    実際に昇格したものの説明メッセージのリストを返す。
    """
    cfg = _load_config()
    ranking_ids = [int(g) for g in cfg["sources"]["ranking"]["genre_ids"]]
    research_ids = [int(g) for g in cfg.get("research", {}).get("extra_genre_ids", []) or []]
    if not research_ids:
        return []

    baseline = _baseline_avg_likes(rows, MIN_SAMPLE_RAKUTEN)
    if baseline <= 0:
        return []

    messages: list[str] = []
    changed = False
    for row in rows:
        key = row["category_key"]
        if not key.isdigit():
            continue
        genre_id = int(key)
        if genre_id not in research_ids or genre_id in ranking_ids:
            continue
        if row["count"] < MIN_SAMPLE_RAKUTEN:
            continue
        if row["avg_likes"] < baseline * GOOD_MULTIPLIER:
            continue

        research_ids.remove(genre_id)
        ranking_ids.append(genre_id)
        changed = True
        msg = (
            f"🎯 自動昇格: 「{row['category']}」ジャンルを投稿候補に追加しました"
            f"（平均いいね{row['avg_likes']} / 全体平均{baseline:.1f}）"
        )
        messages.append(msg)
        notify(msg, title="rakuten_room: genre promoted")

    if changed:
        cfg["sources"]["ranking"]["genre_ids"] = ranking_ids
        cfg.setdefault("research", {})["extra_genre_ids"] = research_ids
        _save_config(cfg)

    return messages


def suggest_a8_expansion(rows: list[dict]) -> list[str]:
    """反応が良いA8ジャンル（a8_links.yamlのgenreタグ）があれば、
    docs/A8アフィリリンク取得依頼.md に依頼を自動追記する。
    """
    baseline = _baseline_avg_likes(rows, MIN_SAMPLE_A8)
    if baseline <= 0:
        return []

    state = _load_state()
    suggested: dict = state.get("a8_suggestions", {})
    today = date.today()

    messages: list[str] = []
    for row in rows:
        key = row["category_key"]
        if key.isdigit():  # 楽天ジャンルは対象外（そちらは自動昇格の方で扱う）
            continue
        if row["count"] < MIN_SAMPLE_A8:
            continue
        if row["avg_likes"] < baseline * GOOD_MULTIPLIER:
            continue

        last = suggested.get(key)
        if last:
            try:
                if today - date.fromisoformat(last) < timedelta(days=RESUGGEST_AFTER_DAYS):
                    continue
            except ValueError:
                pass

        _append_a8_request(row, baseline)
        suggested[key] = today.isoformat()
        msg = (
            f"💡 提案: 「{row['category']}」系の反応が良好です"
            f"（平均いいね{row['avg_likes']} / 全体平均{baseline:.1f}）。"
            f"A8アフィリリンク取得依頼.md に追記しました"
        )
        messages.append(msg)
        notify(msg, title="rakuten_room: new A8 request added")

    if messages:
        state["a8_suggestions"] = suggested
        _save_state(state)
    return messages


def _append_a8_request(row: dict, baseline: float) -> None:
    today = date.today().isoformat()
    section = f"""

## 追加調査依頼（自動生成 {today}）

「{row['category']}」系の投稿の反応が良好です（平均いいね{row['avg_likes']}件、全体平均{baseline:.1f}件）。
同じジャンルの新しいA8プログラムを探して、以下の表に追記してください
（手順は上の「① Threads自動投稿の準備」と同じです）。

| プログラムID | プログラム名 | 広告主名 | 商品名／備考 | アフィリリンク |
|---|---|---|---|---|
| | （{row['category']}系の新規プログラムをここに） | | | |
"""
    if not A8_REQUEST_DOC.exists():
        A8_REQUEST_DOC.parent.mkdir(parents=True, exist_ok=True)
        A8_REQUEST_DOC.write_text(f"# A8アフィリリンク取得依頼\n{section}", encoding="utf-8")
    else:
        with A8_REQUEST_DOC.open("a", encoding="utf-8") as f:
            f.write(section)
