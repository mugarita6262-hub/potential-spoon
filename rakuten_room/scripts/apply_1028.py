"""2026-10-28 2:55 に一度だけ実行する設定の書き換え（systemd タイマー rr-config2-1028）。

ファイルを丸ごと差し替えると、予約のあとに入った別の変更を消したり、変更があると止まったりするので、
必要な2か所だけを書き換える:
  - sources.seasonal.max_share: 0.2 → 0.1（季節ものは1日の投稿の1割まで）
  - sources.keywords.words に「お試し・お試しセット・ふるさと納税 訳あり・訳あり 食品」を足す
書き換えたあと YAML として読めるか確かめ、読めなければ元に戻す。結果は server.log とスマホ通知に出す。
手元のリポジトリの config.yaml にも、10/28 以降に同じ変更を入れること。
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("RR_ROOT", "/home/kirui/rakuten_room"))  # 試験用に差し替えられる
sys.path.insert(0, str(ROOT))
CFG = ROOT / "config.yaml"
LOG = ROOT / "data" / "server.log"
WORDS = ["お試し", "お試しセット", "ふるさと納税 訳あり", "訳あり 食品"]


def log(msg: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    try:
        from src.notify import notify
        notify(msg, title="rakuten_room: 10/28 config")
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    try:  # .env（通知の宛先 NTFY_TOPIC）を先に読み込む。どの結果でも通知が届くように
        from src.config import load_config
        load_config()
    except Exception:  # noqa: BLE001
        pass
    raw = CFG.read_bytes()
    nl = "\r\n" if b"\r\n" in raw else "\n"
    t = raw.decode("utf-8")
    backup = Path(os.environ.get("RR_BACKUP", "/home/kirui/backups/config.yaml.bak-20261028"))
    if backup.exists():  # 2回目以降は別名で退避（1回目のバックアップを上書きしない）
        backup = backup.with_name(backup.name + datetime.now().strftime("-%H%M%S"))
    shutil.copy2(CFG, backup)
    done = []
    # 1) 季節ものの割合（seasonal ブロックの max_share）
    m = re.search(r"(\n  seasonal:\r?\n(?:    .*\r?\n)*?    max_share: )0\.2([^\r\n]*)", t)
    if m:
        t = t[:m.start()] + m.group(1) + "0.1  # 2026-10-28〜 1日の投稿のうち季節ものは1割まで（いいねが最も低かったため）" + t[m.end():]
        done.append("季節もの 2割→1割")
    # 2) キーワードを足す（keywords ブロックの per_keyword の直前に）
    m = re.search(r"\n  keywords:\r?\n(?:    .*\r?\n)*?    per_keyword:", t)
    if m:
        block = t[m.start():m.end()]
        add = [w for w in WORDS if f"    - {w}{nl}" not in block and f"    - {w}\n" not in block]
        if add:
            ins = "".join(f"    - {w}{nl}" for w in add)
            pos = m.end() - len("    per_keyword:")
            t = t[:pos] + f"    # 2026-10-28〜 いいねが多かった「訳あり・お試し」系に寄せる{nl}" + ins + t[pos:]
            done.append("キーワード " + "・".join(add))
    if not done:
        log("10/28の設定の書き換え: 変更する箇所が見つからなかったので何もしていません（手で確認してください）")
        return
    CFG.write_bytes(t.encode("utf-8"))
    try:
        from src.config import load_config
        c = load_config()
        assert float(c["sources"]["seasonal"]["max_share"]) == 0.1 or "季節もの 2割→1割" not in done
        assert all(w in c["sources"]["keywords"]["words"] for w in WORDS)
    except Exception as e:  # noqa: BLE001
        shutil.copy2(backup, CFG)
        log(f"10/28の設定の書き換えに失敗したので元に戻しました（{e}）。手で確認してください")
        return
    log("10/28の設定に書き換えました: " + " / ".join(done))


if __name__ == "__main__":
    main()
