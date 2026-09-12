"""設定ファイルと環境変数の読み込み。"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DRAFTS_DIR = DATA_DIR / "drafts"
SESSION_DIR = DATA_DIR / "session"
POSTED_FILE = DATA_DIR / "posted.json"


def _load_env() -> None:
    """.env を最小実装で読み込む（python-dotenv 不要）。"""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def load_config() -> dict:
    _load_env()
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    cfg["_app_id"] = os.environ.get("RAKUTEN_APP_ID", "").strip()
    cfg["_access_key"] = os.environ.get("RAKUTEN_ACCESS_KEY", "").strip()
    cfg["_affiliate_id"] = os.environ.get("RAKUTEN_AFFILIATE_ID", "").strip()
    cfg["_threads_token"] = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    cfg["_threads_user_id"] = os.environ.get("THREADS_USER_ID", "").strip()

    for d in (DATA_DIR, DRAFTS_DIR, SESSION_DIR):
        d.mkdir(parents=True, exist_ok=True)
    return cfg


def update_env_value(key: str, value: str) -> None:
    """.env の1行を書き換える（無ければ末尾に追加）。トークン自動延長などで使う。"""
    env_path = ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    out: list[str] = []
    found = False
    for line in lines:
        stripped = line.strip()
        if not found and stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k == key:
                out.append(f"{key}={value}")
                found = True
                continue
        out.append(line)
    if not found:
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[key] = value
