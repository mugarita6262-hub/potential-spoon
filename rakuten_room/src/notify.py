"""ntfy.sh でスマホにプッシュ通知を送る。

アカウント登録不要・無料。.env の NTFY_TOPIC が設定されていれば送信する
（未設定なら何もしない）。使い方は README / SETUP_THREADS.md 参照。
"""
from __future__ import annotations

import os

import requests


def notify(message: str, title: str = "rakuten_room") -> None:
    """title はHTTPヘッダーに載るのでASCII文字のみにすること（日本語不可）。
    本文(message)は日本語でOK（UTF-8のボディとして送る）。
    """
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    try:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Content-Type": "text/plain; charset=utf-8"},
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  通知送信に失敗（無視して続行）: {exc}")
