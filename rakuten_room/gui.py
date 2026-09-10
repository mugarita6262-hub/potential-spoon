"""楽天ROOM 投稿ツール — GUI（Tkinter・追加インストール不要）。

起動: rakuten_room.bat をダブルクリック
"""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox

ROOT = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
DRAFTS = ROOT / "data" / "drafts"
POSTED = ROOT / "data" / "posted.json"

# ---- パレット ----
BG = "#15151c"
CARD = "#1e1e28"
LINE = "#2c2c3a"
TXT = "#e6e6ef"
MUTED = "#8b8b9e"
ACCENT = "#e10000"        # 楽天レッド
ACCENT_HOVER = "#ff2a2a"
OK = "#43d17a"
TERM_BG = "#0d0d12"
TERM_TXT = "#cfd2dc"


class Btn(tk.Label):
    """フラットなクリック可能ボタン（ホバー付き）。"""

    def __init__(self, master, text, command, *, primary=False, small=False):
        self.bg = ACCENT if primary else CARD
        self.hover = ACCENT_HOVER if primary else LINE
        fg = "#ffffff" if primary else TXT
        pad = (10, 6) if small else (16, 12)
        super().__init__(master, text=text, bg=self.bg, fg=fg,
                         font=("Yu Gothic UI", 11 if small else 13,
                               "bold" if primary else "normal"),
                         padx=pad[0], pady=pad[1], cursor="hand2")
        self._cmd = command
        self._on = True
        self._fg_on = fg
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self._on and self.config(bg=self.hover))
        self.bind("<Leave>", lambda e: self._on and self.config(bg=self.bg))

    def _click(self, _e):
        if self._on:
            self._cmd()

    def set_enabled(self, on: bool):
        self._on = on
        self.config(bg=self.bg, fg=self._fg_on if on else MUTED)


class App:
    def __init__(self, master: tk.Tk):
        self.m = master
        master.title("楽天ROOM 投稿ツール")
        master.geometry("880x640")
        master.minsize(720, 520)
        master.configure(bg=BG)

        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue[str] = queue.Queue()
        self.buttons: list[Btn] = []

        # ===== ヘッダー =====
        head = tk.Frame(master, bg=BG)
        head.pack(fill="x", padx=20, pady=(16, 4))
        tk.Label(head, text="楽天ROOM 投稿ツール", bg=BG, fg=TXT,
                 font=("Yu Gothic UI", 17, "bold")).pack(side="left")
        tk.Frame(head, bg=ACCENT, width=4, height=22).pack(side="left", padx=12)
        self.acct = tk.Label(head, text="", bg=BG, fg=MUTED, font=("Yu Gothic UI", 10))
        self.acct.pack(side="left")

        # ===== 状況カード =====
        self.card = tk.Frame(master, bg=CARD)
        self.card.pack(fill="x", padx=20, pady=8)
        self.card_line1 = tk.Label(self.card, text="", bg=CARD, fg=TXT, anchor="w",
                                   font=("Yu Gothic UI", 11), padx=14)
        self.card_line1.pack(fill="x", pady=(10, 2))
        self.card_line2 = tk.Label(self.card, text="", bg=CARD, fg=MUTED, anchor="w",
                                   font=("Yu Gothic UI", 10), padx=14)
        self.card_line2.pack(fill="x", pady=(0, 4))
        pbar_wrap = tk.Frame(self.card, bg=LINE, height=8)
        pbar_wrap.pack(fill="x", padx=14, pady=(0, 12))
        pbar_wrap.pack_propagate(False)
        self.pbar = tk.Frame(pbar_wrap, bg=OK)
        self.pbar.place(x=0, y=0, relheight=1, relwidth=0)

        # ===== 主ボタン =====
        main = tk.Frame(master, bg=BG)
        main.pack(fill="x", padx=20, pady=(4, 2))
        b = Btn(main, "▶  今日の投稿をする  (準備 → タブを開く)", lambda: self.run("run"),
                primary=True)
        b.pack(fill="x", ipady=2)
        self.buttons.append(b)

        row2 = tk.Frame(master, bg=BG)
        row2.pack(fill="x", padx=20, pady=6)
        self.del_count = tk.IntVar(value=100)
        del_wrap = tk.Frame(row2, bg=CARD)
        del_wrap.pack(side="left")
        b = Btn(del_wrap, "🗑  古い投稿を削除", self.run_prune, small=True)
        b.pack(side="left"); self.buttons.append(b)
        tk.Spinbox(del_wrap, from_=5, to=500, increment=5, width=5,
                   textvariable=self.del_count, bg=CARD, fg=TXT, buttonbackground=LINE,
                   relief="flat", highlightthickness=0, font=("Consolas", 11),
                   insertbackground=TXT).pack(side="left", padx=(0, 8), pady=6)
        for txt, cmd in [("プレビュー", lambda: self.run("prune")),
                         ("状況を更新", self.refresh_status),
                         ("設定を開く", self.open_config)]:
            bb = Btn(row2, txt, cmd, small=True)
            bb.pack(side="left", padx=(8, 0)); self.buttons.append(bb)

        row3 = tk.Frame(master, bg=BG)
        row3.pack(fill="x", padx=20, pady=(0, 6))
        tk.Label(row3, text="個別:", bg=BG, fg=MUTED,
                 font=("Yu Gothic UI", 9)).pack(side="left", padx=(0, 6))
        for txt, args in [("初回ログイン", ("login",)), ("準備だけ", ("prepare",)),
                          ("投稿だけ", ("post",))]:
            bb = Btn(row3, txt, lambda a=args: self.run(*a), small=True)
            bb.pack(side="left", padx=4); self.buttons.append(bb)
        self.stop_btn = Btn(row3, "■ 中断", self.stop, small=True)
        self.stop_btn.pack(side="right"); self.stop_btn.set_enabled(False)

        # ===== ログ =====
        logwrap = tk.Frame(master, bg=LINE)
        logwrap.pack(fill="both", expand=True, padx=20, pady=8)
        self.log = tk.Text(logwrap, wrap="word", bg=TERM_BG, fg=TERM_TXT,
                           font=("Consolas", 10), relief="flat", padx=12, pady=10,
                           insertbackground=TERM_TXT, highlightthickness=0)
        sb = tk.Scrollbar(logwrap, command=self.log.yview, bg=CARD,
                          troughcolor=TERM_BG, relief="flat", width=12)
        self.log.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_config("dim", foreground=MUTED)
        self.log.tag_config("ok", foreground=OK)

        # ===== 入力バー =====
        bar = tk.Frame(master, bg=BG)
        bar.pack(fill="x", padx=20, pady=(0, 14))
        tk.Label(bar, text="ログが『Enter待ち』で止まったら →", bg=BG, fg=MUTED,
                 font=("Yu Gothic UI", 10)).pack(side="left")
        self.entry = tk.Entry(bar, bg=CARD, fg=TXT, relief="flat", font=("Consolas", 11),
                              insertbackground=TXT, highlightthickness=1,
                              highlightbackground=LINE, highlightcolor=ACCENT)
        self.entry.pack(side="left", fill="x", expand=True, padx=8, ipady=5)
        self.entry.bind("<Return>", lambda e: self.send())
        Btn(bar, "送信 (Enter)", self.send, small=True).pack(side="left")

        self._log("『▶ 今日の投稿をする』で準備〜投稿まで一気に進みます。\n", "dim")
        self._log("初回は『初回ログイン』を先に。削除は空きを作るため定期的に。\n\n", "dim")
        self.refresh_status()
        self.m.after(80, self._drain)

    # ---------- 状況カード ----------
    def refresh_status(self):
        today = date.today().isoformat()
        plan = _read_json(DRAFTS / f"{today}_plan.json") or {}
        target = int(plan.get("target_count") or 10)
        done = _posted_today(today)
        drafts_ok = (DRAFTS / f"{today}_drafts.json").exists()
        caps_ok = (DRAFTS / f"{today}_captions.json").exists()

        reasons = plan.get("reasons") or []
        tag = "  🎯 " + " / ".join(reasons) if reasons else ""
        self.card_line1.config(text=f"今日 {today}{tag}")
        state = "準備OK" if (drafts_ok and caps_ok) else "未準備"
        left = max(0, target - done)
        self.card_line2.config(
            text=f"投稿 {done} / {target} 件"
                 + (f"（あと {left}）" if left else "  ✅ 目標達成")
                 + f"   ・ {state}")
        self.pbar.place(relwidth=min(1.0, done / target if target else 0))
        self.pbar.config(bg=OK if done >= target else ACCENT)

    # ---------- コマンド実行 ----------
    def run_prune(self):
        self.run("prune", "--commit", "--max", str(self.del_count.get()))

    def run(self, *args: str):
        if self.proc and self.proc.poll() is None:
            self._log("\n[!] 前の処理がまだ動いています。『中断』するか終了を待ってください。\n")
            return
        self._log(f"\n$ {' '.join(args)}\n", "dim")
        self._log("─" * 64 + "\n", "dim")
        import os
        try:
            self.proc = subprocess.Popen(
                [str(PY), "-u", "-m", "src.main", *args], cwd=str(ROOT),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                     "PYTHONUNBUFFERED": "1"},
            )
        except Exception as exc:  # noqa: BLE001
            self._log(f"[起動失敗] {exc}\n")
            return
        self._log("実行中...\n", "dim")
        for b in self.buttons:
            b.set_enabled(False)
        self.stop_btn.set_enabled(True)
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc: subprocess.Popen):
        assert proc.stdout is not None
        for line in proc.stdout:
            self.q.put(line)
        proc.wait()
        self.q.put(f"\x00DONE:{proc.returncode}")

    def send(self):
        if self.proc and self.proc.poll() is None and self.proc.stdin:
            txt = self.entry.get()
            try:
                self.proc.stdin.write(txt + "\n")
                self.proc.stdin.flush()
                self._log(f"> {txt}\n", "dim")
            except Exception as exc:  # noqa: BLE001
                self._log(f"[送信失敗] {exc}\n")
            self.entry.delete(0, "end")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self._log("\n[中断しました]\n")

    def open_config(self):
        import os
        try:
            os.startfile(str(ROOT / "config.yaml"))  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            self._log(f"[開けませんでした] {exc}\n")

    # ---------- ログ描画 ----------
    def _drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item.startswith("\x00DONE:"):
                    code = item.split(":", 1)[1]
                    self._log(f"\n[完了 code={code}]\n",
                              "ok" if code == "0" else "dim")
                    for b in self.buttons:
                        b.set_enabled(True)
                    self.stop_btn.set_enabled(False)
                    self.refresh_status()
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.m.after(80, self._drain)

    def _log(self, text: str, tag: str | None = None):
        self.log.insert("end", text, tag or ())
        self.log.see("end")


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _posted_today(today: str) -> int:
    data = _read_json(POSTED) or []
    return sum(1 for r in data
              if r.get("kind") == "posted" and str(r.get("posted_at", "")).startswith(today))


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
