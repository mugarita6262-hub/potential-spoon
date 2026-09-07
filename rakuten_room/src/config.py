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

    for d in (DATA_DIR, DRAFTS_DIR, SESSION_DIR):
        d.mkdir(parents=True, exist_ok=True)
    return cfg
