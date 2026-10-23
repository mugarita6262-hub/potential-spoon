"""その日の「予定と実績」を server.log から集計し、毎晩スマホに通知する（2026-10-18 追加）。

ユーザーの指示: 不備を後から報告するのではなく、毎日の予定と実績を並べて見られるようにする。
room_collect（毎晩23時台）の最後に呼ぶ。数字は各ジョブがログに出す完了行から読む。
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from .config import DATA_DIR, load_config

LOG = DATA_DIR / "server.log"
# ジョブごとに「実績」として拾う完了行と、その中の件数
RESULT_RE = {
    "room_post": re.compile(r"(\d+) 件投稿（"),
    "room_like": re.compile(r"いいね回り完了: (\d+) 件"),
    "room_follow": re.compile(r"フォロー回り完了: (\d+) 件"),
    "room_unfollow": re.compile(r"フォロー解除 (\d+) 件"),
    "room_prune": re.compile(r"削除完了: (\d+) 件"),
    "sitedrop": re.compile(r"(Threads投稿完了)"),
    "trivia": re.compile(r"(Threads投稿完了)"),
    "calendar": re.compile(r"(Threads投稿完了)"),
    "instagram": re.compile(r"(Instagram投稿完了)"),
    "site": re.compile(r"(サイトを生成しました)"),
    "prepare": re.compile(r"(キャプションを自動生成)"),
}
LABEL = {"room_post": "ROOM投稿", "room_like": "いいね", "room_follow": "フォロー", "room_unfollow": "フォロー解除",
         "room_prune": "古い投稿の削除", "sitedrop": "Threads値下がり速報", "trivia": "Threads豆知識",
         "calendar": "Threadsセール告知", "instagram": "Instagram", "site": "サイト更新", "prepare": "ROOM候補選び"}


def _targets(cfg: dict) -> dict:
    """1日の目標件数（件数で見るジョブだけ）。投稿はその日の plan（セール倍率込み）を優先。"""
    from .captions import load_plan
    ec = cfg.get("engage", {}) or {}
    plan = load_plan()
    return {"room_post": int(plan.get("target_count") or cfg.get("post_count", 0)),
            "room_like": int(ec.get("daily_likes", 0)), "room_follow": int(ec.get("daily_follows", 0)),
            "room_prune": int(ec.get("daily_prune", 0))}
    # フォロー解除は「返してくれない人」がいなければ0件で正常なので、件数ではなく実行回数で見る（2026-10-22）


def build(day: str | None = None) -> str:
    day = day or date.today().isoformat()
    lines = LOG.read_text(encoding="utf-8", errors="ignore").splitlines()
    sched = [l for l in lines if l.startswith(f"[{day}") and "本日のスケジュール" in l]
    plan = {j: [t.strip(" '") for t in ts.split(",") if t.strip()]
            for j, ts in re.findall(r"(\w+)=\[([^\]]*)\]", sched[-1])} if sched else {}
    runs, got = defaultdict(int), defaultdict(int)
    cur = None
    for l in lines:
        m = re.match(r"\[(\S+) [\d:]+\] \[自動実行\] (\w+)", l)
        if m:
            cur = m.group(2) if m.group(1) == day else None
            if cur:
                runs[cur] += 1
            continue
        if cur in RESULT_RE:
            r = RESULT_RE[cur].search(l)
            if r:
                got[cur] += int(r.group(1)) if r.group(1).isdigit() else 1
    tg = _targets(load_config())
    out, bad = [], []
    for job, times in plan.items():
        if job not in LABEL:
            continue
        if job in tg:
            ok = got[job] >= tg[job] * 0.9
            s = f"{LABEL[job]}: {got[job]}/{tg[job]}件（{runs[job]}/{len(times)}回）"
        else:
            ok = runs[job] >= len(times)
            s = f"{LABEL[job]}: 実行{runs[job]}/{len(times)}回・成功{got[job]}"
        out.append(("○ " if ok else "✕ ") + s)
        if not ok:
            bad.append(LABEL[job])
    # ROOM投稿の時間配分（夜まで出ているか）
    posts_by_run = []
    cur = None
    for l in lines:
        m = re.match(r"\[(\S+) (\d\d:\d\d):\d\d\] \[自動実行\] room_post", l)
        if m:
            cur = m.group(2) if m.group(1) == day else None
            continue
        if cur:
            r = RESULT_RE["room_post"].search(l)
            if r:
                posts_by_run.append(f"{cur}={r.group(1)}")
    if posts_by_run:
        out.append("  ROOM投稿の回ごと: " + " ".join(posts_by_run))
    # 件数が足りていても、0件の回があれば偏っている（10/16〜18は18時台で150件に達し、20〜22時が0件だった）
    n_runs = len(plan.get("room_post", []))
    if n_runs and len(posts_by_run) < runs["room_post"]:
        out.append(f"✕ ROOM投稿: {runs['room_post'] - len(posts_by_run)}回は0件（時間帯が偏っている）")
        bad.append("ROOM投稿の時間配分")
    # フォロー中の人数（ROOMの上限は1万人。2026-10-23 時点で1日+500人ほど増えている）
    try:
        import json as _json
        st = _json.loads((DATA_DIR / "room_stats.json").read_text(encoding="utf-8"))
        last = st[sorted(st)[-1]]
        warn = last.get("following", 0) >= 9000
        out.append(f"{'✕' if warn else '○'} フォロワー {last.get('followers', 0):,}人 / フォロー中 {last.get('following', 0):,}人（上限1万人）")
        if warn:
            bad.append("フォロー中が上限1万人に近い")
    except Exception:  # noqa: BLE001
        pass
    head = f"{day} 予定と実績" + (f"（要確認: {'・'.join(bad)}）" if bad else "（すべて予定どおり）")
    return head + "\n" + "\n".join(out)


def send(day: str | None = None) -> None:
    from .notify import notify
    text = build(day)
    print(text)
    notify(text, title="rakuten_room daily report")


if __name__ == "__main__":
    import sys
    print(build(sys.argv[1] if len(sys.argv) > 1 else None))
