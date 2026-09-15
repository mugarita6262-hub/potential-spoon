"""Threads/Instagram投稿ジョブの多重実行を防ぐプロセス間ロック。

サーバーのスケジューラ（webapp.py内蔵、threading.Lockで同一プロセス内は排他済み）と、
SSHで直接叩く `python -m src.main sns` 等の手動実行は別プロセスなので、
threading.Lockだけでは守れない。2026-09-15に実際にこれが原因で同じ商品が
2回ずつ投稿される事故が起きた（手動sns実行とスケジューラの再起動後キャッチアップ
実行がほぼ同時に走り、どちらも「まだ投稿していない商品」を独立に選んでしまった）。
ロックファイルの存在で両者をまたいで排他する。
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

_LOCK_PATH = Path(__file__).resolve().parent.parent / "data" / ".posting.lock"
_STALE_SECONDS = 600  # これ以上古ければ前回のクラッシュ等とみなして奪い取る


@contextmanager
def posting_lock():
    """取得できればTrue、既に他プロセスが投稿中ならFalseをyieldする（呼び出し側はFalseならスキップする）。"""
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _try_acquire():
        yield False
        return
    try:
        yield True
    finally:
        try:
            _LOCK_PATH.unlink()
        except FileNotFoundError:
            pass


def _try_acquire() -> bool:
    try:
        fd = os.open(str(_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            age = time.time() - _LOCK_PATH.stat().st_mtime
        except FileNotFoundError:
            return _try_acquire()
        if age > _STALE_SECONDS:
            try:
                _LOCK_PATH.unlink()
            except FileNotFoundError:
                pass
            return _try_acquire()
        return False
