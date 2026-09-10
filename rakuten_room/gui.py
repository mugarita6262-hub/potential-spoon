"""楽天ROOM 投稿ツール — GUI（Tkinter・追加インストール不要）。
起動: rakuten_room.bat をダブルクリック
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox

import yaml

ROOT = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
CONFIG = ROOT / "config.yaml"
DRAFTS = ROOT / "data" / "drafts"
POSTED = ROOT / "data" / "posted.json"

BG = "#15151c"
CARD = "#1e1e28"
LINE = "#33333f"
TXT = "#e8e8f0"
MUTED = "#9a9aae"
ACCENT = "#e10000"
ACCENT_HI = "#ff2d2d"
GO = "#2e7d32"
GO_HI = "#3aa03f"
OKC = "#43d17a"
TERM_BG = "#0c0c11"
TERM_TXT = "#d2d5df"

WAIT_HINTS = ("Enter", "enter", "押してください", "よろしければ", "完了したら")

GENRES = [
    (0, "総合ランキング"),
    (100939, "美容・コスメ・香水"),
    (100804, "日用品雑貨・文房具"),
    (100227, "食品"),
    (558885, "スイーツ・お菓子"),
    (100371, "レディースファッション"),
    (551177, "メンズファッション"),
    (216131, "キッズ・ベビー・マタニティ"),
    (558929, "靴"),
    (100804, "インテリア・寝具・収納"),
    (562637, "家電"),
    (100533, "キッチン用品・食器"),
    (510915, "ドリンク"),
    (100804, "医薬品・コンタクト・介護"),
]


# ---------- config 読み書き ----------
def load_cfg() -> dict:
    try:
        return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def save_cfg(cfg: dict) -> None:
    header = (
        "# 楽天ROOM 投稿ツール 設定\n"
        "# 主な項目は GUI の『⚙ 設定』から変更できます（このファイルを直接編集する必要はありません）\n"
        "# scoring / per_genre / favorites などの詳細はここで調整します\n\n"
    )
    CONFIG.write_text(
        header + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False,
                                default_flow_style=False),
        encoding="utf-8")


def cfg_get(cfg: dict, path: str, default):
    cur = cfg
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def cfg_put(cfg: dict, path: str, value) -> None:
    keys = path.split(".")
    cur = cfg
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


class Btn(tk.Label):
    def __init__(self, master, text, command, *, kind="normal", small=False):
        colors = {"primary": (ACCENT, ACCENT_HI, "#fff"),
                  "go": (GO, GO_HI, "#fff"), "normal": (CARD, LINE, TXT)}
        self.c0, self.c1, fg = colors[kind]
        f = ("Yu Gothic UI", 10 if small else 13, "bold" if kind != "normal" else "normal")
        super().__init__(master, text=text, bg=self.c0, fg=fg, font=f,
                         padx=12 if small else 18, pady=6 if small else 13, cursor="hand2")
        self._cmd, self._on, self._fg = command, True, fg
        self.bind("<Button-1>", lambda e: self._on and self._cmd())
        self.bind("<Enter>", lambda e: self._on and self.config(bg=self.c1))
        self.bind("<Leave>", lambda e: self._on and self.config(bg=self.c0))

    def enable(self, on: bool):
        self._on = on
        self.config(bg=self.c0, fg=self._fg if on else MUTED,
                    cursor="hand2" if on else "arrow")


def spin(master, var, lo, hi, inc=1, w=5):
    return tk.Spinbox(master, from_=lo, to=hi, increment=inc, width=w, textvariable=var,
                      bg=CARD, fg=TXT, relief="flat", buttonbackground=LINE,
                      insertbackground=TXT, font=("Consolas", 10), highlightthickness=0)


# ======================= 設定ウィンドウ =======================
class SettingsWin(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("設定")
        self.configure(bg=BG)
        self.geometry("560x680")
        self.transient(master)
        self.grab_set()
        cfg = load_cfg()

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=18, pady=14)

        self.vars: dict[str, tk.Variable] = {}

        def section(title):
            tk.Label(wrap, text=title, bg=BG, fg=ACCENT_HI,
                     font=("Yu Gothic UI", 11, "bold")).pack(anchor="w", pady=(12, 4))

        def row(label, path, default, lo, hi, inc=1, hint=""):
            r = tk.Frame(wrap, bg=BG); r.pack(fill="x", pady=2)
            tk.Label(r, text=label, bg=BG, fg=TXT, width=16, anchor="w",
                     font=("Yu Gothic UI", 10)).pack(side="left")
            v = tk.DoubleVar(value=float(cfg_get(cfg, path, default))) if inc < 1 \
                else tk.IntVar(value=int(cfg_get(cfg, path, default)))
            self.vars[path] = v
            spin(r, v, lo, hi, inc).pack(side="left")
            if hint:
                tk.Label(r, text=hint, bg=BG, fg=MUTED,
                         font=("Yu Gothic UI", 8)).pack(side="left", padx=6)

        section("投稿")
        row("1日に投稿する数", "post_count", 10, 1, 50, hint="1日で新しく紹介する商品の数")
        row("一度に開くタブ数", "post_batch_size", 4, 1, 50,
            hint="ボタン1回で開く数。少なくすると朝昼夜など数回に分けて投稿できます")

        section("セール日の増量")
        self.v_sale = tk.BooleanVar(value=bool(cfg_get(cfg, "sale_boost.enabled", True)))
        tk.Checkbutton(wrap, text="セール・イベント日に投稿数を増やす", variable=self.v_sale,
                       bg=BG, fg=TXT, selectcolor=CARD, activebackground=BG,
                       font=("Yu Gothic UI", 10)).pack(anchor="w")
        row("5と0のつく日 倍率", "sale_boost.five_ten_day_multiplier", 1.3, 1.0, 3.0, 0.1)
        row("SALE/マラソン 倍率", "sale_boost.event_multiplier", 1.8, 1.0, 3.0, 0.1)
        tk.Label(wrap, text="セール期間（1行に「名前, 開始日, 終了日」 例: SALE, 2026-09-04, 2026-09-11）",
                 bg=BG, fg=MUTED, font=("Yu Gothic UI", 8)).pack(anchor="w", pady=(6, 2))
        self.ev_text = tk.Text(wrap, height=4, bg=CARD, fg=TXT, relief="flat",
                               font=("Consolas", 9), insertbackground=TXT,
                               highlightthickness=1, highlightbackground=LINE)
        self.ev_text.pack(fill="x")
        for e in cfg_get(cfg, "sale_boost.manual_events", []) or []:
            self.ev_text.insert("end",
                                f"{e.get('name','SALE')}, {e.get('start','')}, {e.get('end','')}\n")

        section("対象ジャンル（候補を集める楽天ランキング）")
        cur_g = set(int(x) for x in cfg_get(cfg, "sources.ranking.genre_ids", []) or [])
        self.g_vars = {}
        grid = tk.Frame(wrap, bg=BG); grid.pack(fill="x")
        seen = set()
        i = 0
        for gid, name in GENRES:
            if gid in seen:
                continue
            seen.add(gid)
            v = tk.BooleanVar(value=(gid in cur_g))
            self.g_vars[gid] = v
            tk.Checkbutton(grid, text=name, variable=v, bg=BG, fg=TXT, selectcolor=CARD,
                           activebackground=BG, font=("Yu Gothic UI", 9), anchor="w"
                           ).grid(row=i // 2, column=i % 2, sticky="w", padx=2)
            i += 1

        section("古い投稿の削除")
        r = tk.Frame(wrap, bg=BG); r.pack(fill="x", pady=2)
        tk.Label(r, text="この日付より後は消さない", bg=BG, fg=TXT, width=20, anchor="w",
                 font=("Yu Gothic UI", 10)).pack(side="left")
        self.v_before = tk.StringVar(value=str(cfg_get(cfg, "prune.only_before", "2025-01-01")))
        tk.Entry(r, textvariable=self.v_before, width=12, bg=CARD, fg=TXT, relief="flat",
                 font=("Consolas", 10), insertbackground=TXT).pack(side="left")
        row("1回の削除数", "prune.max_delete_per_run", 15, 5, 500, 5)

        btns = tk.Frame(self, bg=BG); btns.pack(fill="x", padx=18, pady=(0, 14))
        Btn(btns, "保存して閉じる", self.save, kind="primary", small=True).pack(side="right")
        Btn(btns, "キャンセル", self.destroy, small=True).pack(side="right", padx=8)

    def save(self):
        cfg = load_cfg()
        for path, v in self.vars.items():
            val = v.get()
            cfg_put(cfg, path, round(val, 2) if isinstance(val, float) else int(val))
        cfg_put(cfg, "sale_boost.enabled", bool(self.v_sale.get()))
        cfg_put(cfg, "prune.only_before", self.v_before.get().strip())

        events = []
        for ln in self.ev_text.get("1.0", "end").splitlines():
            parts = [p.strip() for p in ln.split(",")]
            if len(parts) >= 3 and parts[1] and parts[2]:
                events.append({"name": parts[0] or "SALE",
                               "start": parts[1], "end": parts[2]})
        cfg_put(cfg, "sale_boost.manual_events", events)

        gids = [gid for gid, v in self.g_vars.items() if v.get()]
        if gids:
            cfg_put(cfg, "sources.ranking.genre_ids", gids)

        try:
            save_cfg(cfg)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("保存失敗", str(exc))
            return
        self.destroy()


# ======================= メイン画面 =======================
class App:
    def __init__(self, m: tk.Tk):
        self.m = m
        m.title("楽天ROOM 投稿ツール")
        m.geometry("860x640")
        m.minsize(700, 540)
        m.configure(bg=BG)
        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue = queue.Queue()
        self.waiting = False
        self._tail = ""
        self._idle = 0

        h = tk.Frame(m, bg=BG); h.pack(fill="x", padx=22, pady=(16, 2))
        tk.Label(h, text="楽天ROOM 投稿ツール", bg=BG, fg=TXT,
                 font=("Yu Gothic UI", 17, "bold")).pack(side="left")
        Btn(h, "⚙ 設定", self.open_settings, small=True).pack(side="right")

        c = tk.Frame(m, bg=CARD); c.pack(fill="x", padx=22, pady=10)
        self.cl1 = tk.Label(c, text="", bg=CARD, fg=TXT, anchor="w", padx=16,
                            font=("Yu Gothic UI", 11)); self.cl1.pack(fill="x", pady=(12, 2))
        self.cl2 = tk.Label(c, text="", bg=CARD, fg=MUTED, anchor="w", padx=16,
                            font=("Yu Gothic UI", 10)); self.cl2.pack(fill="x", pady=(0, 2))
        self.cl3 = tk.Label(c, text="", bg=CARD, fg="#ffd166", anchor="w", padx=16,
                            font=("Yu Gothic UI", 10)); self.cl3.pack(fill="x", pady=(0, 6))
        pwf = tk.Frame(c, bg=LINE, height=8); pwf.pack(fill="x", padx=16, pady=(0, 14))
        pwf.pack_propagate(False)
        self.pbar = tk.Frame(pwf, bg=ACCENT); self.pbar.place(x=0, y=0, relheight=1, relwidth=0)

        pa = tk.Frame(m, bg=BG); pa.pack(fill="x", padx=22)
        self.primary = Btn(pa, "▶  おまかせ（投稿 → いいね回り → フォロー回り）",
                           self.do_run, kind="primary")
        self.primary.pack(fill="x", ipady=3)
        prow = tk.Frame(pa, bg=BG); prow.pack(fill="x", pady=(2, 0))
        tk.Label(prow, text="この1つで1日ぶんの作業が順番に進みます。",
                 bg=BG, fg=MUTED, font=("Yu Gothic UI", 9)).pack(side="left")
        self.postonly_btn = Btn(prow, "投稿だけ", lambda: self.launch("run"), small=True)
        self.postonly_btn.pack(side="right")

        # いいね回り・フォロー回り
        eg = tk.Frame(m, bg=BG); eg.pack(fill="x", padx=22, pady=(10, 2))
        self.v_like = tk.IntVar(value=30)
        self.v_follow = tk.IntVar(value=15)
        w1 = tk.Frame(eg, bg=CARD); w1.pack(side="left")
        self.like_btn = Btn(w1, "♡ いいね回り", lambda: self.launch("like", "--n",
                            str(self.v_like.get())), small=True)
        self.like_btn.pack(side="left")
        spin(w1, self.v_like, 5, 200, 5, w=4).pack(side="left", padx=(2, 8))
        w2 = tk.Frame(eg, bg=CARD); w2.pack(side="left", padx=(10, 0))
        self.follow_btn = Btn(w2, "＋ フォロー回り", lambda: self.launch("follow", "--n",
                              str(self.v_follow.get())), small=True)
        self.follow_btn.pack(side="left")
        spin(w2, self.v_follow, 3, 80, 3, w=4).pack(side="left", padx=(2, 8))
        self.unf_btn = Btn(eg, "フォロー整理", lambda: self.launch("unfollow"), small=True)
        self.unf_btn.pack(side="left", padx=(10, 0))
        self.eg_lbl = tk.Label(eg, text="", bg=BG, fg=MUTED, font=("Yu Gothic UI", 9))
        self.eg_lbl.pack(side="left", padx=(12, 0))

        sa = tk.Frame(m, bg=BG); sa.pack(fill="x", padx=22, pady=(6, 8))
        self.spin = tk.IntVar(value=100)
        wr = tk.Frame(sa, bg=CARD); wr.pack(side="left")
        self.prune_btn = Btn(wr, "🗑 古い投稿を削除", self.do_prune, small=True)
        self.prune_btn.pack(side="left")
        spin(wr, self.spin, 10, 500, 10).pack(side="left", padx=(2, 8))
        tk.Label(sa, text="件（登録上限の余裕づくり）", bg=BG, fg=MUTED,
                 font=("Yu Gothic UI", 9)).pack(side="left", padx=(4, 0))
        self.sub_btns = [self.prune_btn, self.like_btn, self.follow_btn, self.unf_btn,
                         self.postonly_btn]

        adv = tk.Frame(m, bg=BG); adv.pack(fill="x", padx=22)
        b = Btn(adv, "初回ログイン", lambda: self.launch("login"), small=True)
        b.pack(side="left"); self.sub_btns.append(b)
        self.stop_btn = Btn(adv, "■ 中断", self.stop, small=True)
        self.stop_btn.pack(side="right"); self.stop_btn.enable(False)

        lw = tk.Frame(m, bg=LINE); lw.pack(fill="both", expand=True, padx=22, pady=10)
        self.log = tk.Text(lw, wrap="word", bg=TERM_BG, fg=TERM_TXT, font=("Consolas", 10),
                           relief="flat", padx=12, pady=10, insertbackground=TERM_TXT,
                           highlightthickness=0)
        sc = tk.Scrollbar(lw, command=self.log.yview, width=12)
        self.log.config(yscrollcommand=sc.set)
        sc.pack(side="right", fill="y"); self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_config("dim", foreground=MUTED)
        self.log.tag_config("ok", foreground=OKC)

        self.wait_bar = tk.Frame(m, bg=BG)
        self.wait_lbl = tk.Label(self.wait_bar, text="", bg=BG, fg="#ffd166",
                                 font=("Yu Gothic UI", 10))
        self.wait_lbl.pack(side="left", padx=(22, 8), pady=(0, 12))
        self.cont_btn = Btn(self.wait_bar, "▶  続ける", self.send_enter, kind="go", small=True)
        self.cont_btn.pack(side="left", pady=(0, 12))

        self._say("『▶ 今日の投稿をする』で 準備 → 投稿タブ まで進みます。\n", "dim")
        self._say("2回目以降は準備を自動でスキップ。初回のみ『初回ログイン』を先に。\n\n", "dim")
        self.refresh()
        self.m.after(80, self._drain)
        self._auto_refresh()

    def open_settings(self):
        SettingsWin(self.m)

    def _auto_refresh(self):
        if not (self.proc and self.proc.poll() is None):
            self.refresh()
        self.m.after(4000, self._auto_refresh)

    def refresh(self):
        t = date.today().isoformat()
        plan = _json(DRAFTS / f"{t}_plan.json") or {}
        target = int(plan.get("target_count") or _cfg_int("post_count", 10))
        done = _posted_today(t)
        reasons = plan.get("reasons") or []
        self.cl1.config(text=f"今日 {t}" + ("   🎯 " + " / ".join(reasons) if reasons else ""))
        prepared = (DRAFTS / f"{t}_captions.json").exists()
        left = max(0, target - done)
        self.cl2.config(text=(f"投稿 {done} / {target} 件"
                              + (f"（あと {left}）" if left else "  ✅ 目標達成")
                              + ("   ・準備OK" if prepared else "   ・未準備")))
        self.pbar.place(relwidth=min(1.0, done / target) if target else 0)
        self.pbar.config(bg=OKC if done >= target else ACCENT)
        adv = _advice(reasons)
        self.cl3.config(text=("🟢 " if adv.get("good") else "・") + adv.get("hint", ""),
                        fg=OKC if adv.get("good") else MUTED)
        es = _engage_status()
        if es:
            self.eg_lbl.config(text="今日: ♡{}/{}  ＋{}/{}".format(
                *es["like"], *es["follow"]))

    def do_run(self):
        self.send_enter() if self.waiting else self.launch("daily")

    def do_prune(self):
        self.launch("prune", "--commit", "--max", str(self.spin.get()))

    def launch(self, *args):
        if self.proc and self.proc.poll() is None:
            self._say("\n[!] まだ処理中です。『中断』するか完了を待ってください。\n", "dim")
            return
        self._set_running(True)
        self._say(f"\n$ {' '.join(args) or 'run'}\n" + "─" * 60 + "\n実行中...\n", "dim")
        try:
            self.proc = subprocess.Popen(
                [str(PY), "-u", "-m", "src.main", *args], cwd=str(ROOT),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                     "PYTHONUNBUFFERED": "1"})
        except Exception as exc:  # noqa: BLE001
            self._say(f"[起動失敗] {exc}\n"); self._set_running(False); return
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, p):
        for line in p.stdout:
            self.q.put(line)
        p.wait()
        self.q.put(f"\x00DONE:{p.returncode}")

    def send_enter(self):
        if self.proc and self.proc.poll() is None and self.proc.stdin:
            try:
                self.proc.stdin.write("\n"); self.proc.stdin.flush()
                self._say("[続行]\n", "dim")
            except Exception as exc:  # noqa: BLE001
                self._say(f"[送信失敗] {exc}\n")
        self._set_waiting(False)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self._say("\n[中断しました]\n", "dim")

    def open_cfg(self):
        try:
            os.startfile(str(CONFIG))  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            self._say(f"[開けません] {exc}\n")

    def _set_running(self, on):
        for b in self.sub_btns:
            b.enable(not on)
        self.stop_btn.enable(on)
        if on:
            self._set_waiting(False)
        else:
            self.primary.enable(True)

    def _set_waiting(self, on):
        self.waiting = on
        if on:
            self.wait_bar.pack(fill="x")
            self.wait_lbl.config(text="ブラウザのタブで『完了』を押し終えたら →")
            self.primary.c0, self.primary.c1 = GO, GO_HI
            self.primary.config(bg=GO, text="▶  投稿できた（続ける）")
            self.primary.enable(True)
        else:
            self.wait_bar.pack_forget()
            self.primary.c0, self.primary.c1 = ACCENT, ACCENT_HI
            self.primary.config(bg=ACCENT, text="▶  今日の投稿をする")

    def _drain(self):
        got = False
        try:
            while True:
                it = self.q.get_nowait()
                got = True
                if it.startswith("\x00DONE:"):
                    code = it.split(":", 1)[1]
                    self._say("\n[完了]\n" if code == "0" else f"\n[終了 code={code}]\n",
                              "ok" if code == "0" else "dim")
                    self._set_running(False); self.refresh()
                else:
                    self._say(it)
                    self._tail = (self._tail + it)[-400:]
        except queue.Empty:
            pass
        self._idle = 0 if got else self._idle + 1
        alive = self.proc and self.proc.poll() is None
        if (alive and not self.waiting and self._idle >= 4
                and any(hh in self._tail[-250:] for hh in WAIT_HINTS)):
            self._set_waiting(True)
        self.m.after(120, self._drain)

    def _say(self, text, tag=None):
        self.log.insert("end", text, tag or ())
        self.log.see("end")


def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _posted_today(t: str) -> int:
    return sum(1 for r in (_json(POSTED) or [])
              if r.get("kind") == "posted" and str(r.get("posted_at", "")).startswith(t))


def _cfg_int(key: str, default: int) -> int:
    try:
        return int((load_cfg() or {}).get(key, default))
    except Exception:  # noqa: BLE001
        return default


def _advice(reasons: list) -> dict:
    try:
        from src.timing import posting_advice
        return posting_advice({}, {"reasons": reasons})
    except Exception:  # noqa: BLE001
        return {}


def _engage_status() -> dict:
    try:
        from src.engage import engage_status
        return engage_status(load_cfg())
    except Exception:  # noqa: BLE001
        return {}


def main():
    if not PY.exists():
        r = tk.Tk(); r.withdraw()
        messagebox.showerror("エラー", f"Python が見つかりません:\n{PY}")
        return
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
