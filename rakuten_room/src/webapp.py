"""サーバー常駐用のWebダッシュボード。SSHせずブラウザから操作・確認する。

起動: python -m src.webapp
（.env の WEBAPP_USER / WEBAPP_PASSWORD でBasic認証。WEBAPP_PORTでポート変更、既定8080）

裏で「1日の中でランダムな時刻に自動実行」するスケジューラも常駐する。
ROOMのpost/like/follow/prune（実Chrome必須）はここには含めない。
ローカルマシンのGUIから引き続き実行すること。
"""
from __future__ import annotations

import functools
import io
import os
import random
import threading
import time
import traceback
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from datetime import time as dtime

from flask import Flask, Response, redirect, render_template_string, request, url_for

from .config import DATA_DIR, load_config

LOG_FILE = DATA_DIR / "server.log"
MAX_LOG_LINES = 300

app = Flask(__name__)

_lock = threading.Lock()
_last_run: dict[str, dict] = {}

# コストが発生しない（Claude APIを使わない）調査系ジョブは高頻度、
# 投稿系（コスト発生・投稿数もコントロールしたい）は低頻度、という前提のラベル
JOBS = {
    "collect": ("調査: 広いジャンルの価格収集（無料・高頻度向け）", False),
    "insights": ("調査: Threadsの反応を集計（無料・高頻度向け）", False),
    "prepare": ("ROOM: 商品選定＋キャプション生成（Claude課金・1日1回想定）", True),
    "sns": ("Threads: 値下がり検知投稿（Claude課金・1日数回想定）", True),
    "a8": ("Threads: A8ローテーション投稿（Claude課金・1日1回想定）", True),
    "digest": ("Threads: ジャンル別売れ筋ダイジェスト（Claude課金・リンクあり）", True),
    "trend": ("Threads: ジャンル価格トレンド速報（Claude課金・リンクなし）", True),
    "calendar": ("Threads: セール・お得日リマインド（Claude課金・リンクなし）", True),
    "trivia": ("Threads: ミニ知識・あるあるネタ（Claude課金・リンクなし）", True),
}


def _log(line: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {line}\n")


def _tail_log(n: int = MAX_LOG_LINES) -> str:
    if not LOG_FILE.exists():
        return "(ログはまだありません)"
    lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    return "\n".join(lines)


def run_job(name: str) -> str:
    """ジョブを実行し、標準出力をキャプチャして記録・返却する。"""
    from . import main as cli

    with _lock:
        cfg = load_config()
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                if name == "collect":
                    cli.cmd_collect(cfg)
                elif name == "prepare":
                    cli.cmd_prepare(cfg)
                elif name == "sns":
                    cli.cmd_sns(cfg)
                elif name == "a8":
                    cli.cmd_a8(cfg)
                elif name == "digest":
                    cli.cmd_digest(cfg)
                elif name == "trend":
                    cli.cmd_trend(cfg)
                elif name == "calendar":
                    cli.cmd_calendar(cfg)
                elif name == "trivia":
                    cli.cmd_trivia(cfg)
                elif name == "insights":
                    cli.cmd_insights(cfg)
                else:
                    raise ValueError(f"unknown job: {name}")
        except Exception:
            buf.write("\n" + traceback.format_exc())
        output = buf.getvalue()
        _last_run[name] = {"at": datetime.now().isoformat(timespec="seconds"),
                            "output": output}
        _log(f"=== {name} ===\n{output}")
        return output


# ---------------- 自動スケジューラ（1日の中でランダムな時刻に実行） ----------------
_schedule_state: dict = {"date": None, "targets": {}, "fired": set()}


def _parse_hm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def _random_times(window: list, n: int, today: date) -> list[datetime]:
    if not window or n <= 0:
        return []
    start = datetime.combine(today, _parse_hm(window[0]))
    end = datetime.combine(today, _parse_hm(window[1]))
    span = (end - start).total_seconds()
    if span <= 0:
        return []
    return sorted(start + timedelta(seconds=random.uniform(0, span)) for _ in range(n))


def _ensure_today_schedule(cfg: dict) -> None:
    today = date.today()
    if _schedule_state["date"] == today:
        return
    sc = cfg.get("server", {}) or {}
    targets = {}
    for job in JOBS:
        window = sc.get(f"{job}_window")
        n = int(sc.get(f"{job}_runs_per_day", 0) or 0)
        if window and n:
            targets[job] = _random_times(window, n, today)
    _schedule_state.update(date=today, targets=targets, fired=set())
    _log("本日のスケジュール: " + (
        ", ".join(f"{k}={[t.strftime('%H:%M') for t in v]}" for k, v in targets.items())
        or "(設定なし)"))


def _scheduler_loop() -> None:
    while True:
        try:
            cfg = load_config()
            if (cfg.get("server", {}) or {}).get("enabled", True):
                _ensure_today_schedule(cfg)
                now = datetime.now()
                for job, times in _schedule_state["targets"].items():
                    for i, t in enumerate(times):
                        key = (job, i)
                        if key in _schedule_state["fired"] or now < t:
                            continue
                        _schedule_state["fired"].add(key)
                        _log(f"[自動実行] {job}（予定 {t.strftime('%H:%M')}）")
                        run_job(job)
        except Exception:
            _log("スケジューラでエラー:\n" + traceback.format_exc())
        time.sleep(300)  # 5分おきにチェック


def start_scheduler() -> None:
    threading.Thread(target=_scheduler_loop, daemon=True).start()


# ---------------- Basic認証 ----------------
def _check_auth(user: str, pw: str) -> bool:
    expected_pw = os.environ.get("WEBAPP_PASSWORD", "")
    return bool(expected_pw) and user == os.environ.get("WEBAPP_USER", "admin") and pw == expected_pw


def requires_auth(f):
    @functools.wraps(f)
    def wrapper(*a, **kw):
        auth = request.authorization
        if not auth or not _check_auth(auth.username or "", auth.password or ""):
            return Response("認証が必要です", 401,
                             {"WWW-Authenticate": 'Basic realm="rakuten_room"'})
        return f(*a, **kw)
    return wrapper


# ---------------- 画面 ----------------
PAGE = """
<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>rakuten_room サーバー管理</title>
<style>
body{font-family:system-ui,"Yu Gothic UI",sans-serif;background:#15151c;color:#e8e8f0;margin:0;padding:20px}
h1{font-size:19px} h2{font-size:15px;color:#9a9aae;margin:0 0 10px}
.card{background:#1e1e28;border:1px solid #33333f;border-radius:8px;padding:16px;margin-bottom:16px}
button{background:#e10000;color:#fff;border:none;border-radius:6px;padding:9px 14px;
       font-size:13px;cursor:pointer;margin:0 8px 8px 0}
button:hover{background:#ff2d2d}
button.free{background:#2e7d32} button.free:hover{background:#3aa03f}
pre{background:#0c0c11;color:#d2d5df;padding:10px;border-radius:6px;overflow:auto;
    max-height:300px;white-space:pre-wrap;font-size:12px}
.meta{color:#9a9aae;font-size:12px;margin-left:8px}
.job{margin-bottom:14px}
</style></head><body>
<h1>rakuten_room サーバー管理</h1>

<div class="card">
  <h2>手動実行</h2>
  {% for name, (label, costly) in jobs.items() %}
  <div class="job">
    <form style="display:inline" method="post" action="{{ url_for('run_route', job=name) }}">
      <button class="{{ 'costly' if costly else 'free' }}" type="submit">{{ label }}</button>
    </form>
    <span class="meta">
      {{ last_run.get(name, {}).get('at', '未実行') }}
    </span>
    {% if last_run.get(name) %}
    <pre>{{ last_run[name]['output'] }}</pre>
    {% endif %}
  </div>
  {% endfor %}
</div>

<div class="card">
  <h2>ログ（直近{{ max_lines }}行）</h2>
  <pre>{{ log_tail }}</pre>
</div>

</body></html>
"""


@app.route("/")
@requires_auth
def index():
    return render_template_string(
        PAGE, jobs=JOBS, last_run=_last_run, log_tail=_tail_log(), max_lines=MAX_LOG_LINES,
    )


@app.route("/run/<job>", methods=["POST"])
@requires_auth
def run_route(job: str):
    if job not in JOBS:
        return "不明なジョブです", 400
    threading.Thread(target=run_job, args=(job,), daemon=True).start()
    time.sleep(1)  # 一覧に「実行中…」が反映されるまでの一瞬の間
    return redirect(url_for("index"))


@app.route("/healthz")
def healthz():
    return "ok"


def main() -> None:
    load_config()  # .env を読み込む（WEBAPP_*や各種APIキーをos.environに反映）
    if not os.environ.get("WEBAPP_PASSWORD"):
        raise SystemExit(
            ".env に WEBAPP_PASSWORD が未設定です。第三者にダッシュボードを触られないよう、"
            "必ず設定してから起動してください（WEBAPP_USERは省略時 'admin'）。"
        )
    start_scheduler()
    port = int(os.environ.get("WEBAPP_PORT", "8080"))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
