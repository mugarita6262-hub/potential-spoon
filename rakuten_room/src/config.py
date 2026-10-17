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


class _NoDupLoader(yaml.SafeLoader):
    """同じキーが2回あると後ろが前を黙って上書きする。2026-10-17に sale_boost を重ねて書き、
    5と0の日・セール時の投稿増が丸ごと無効になった。重複は読み込みの時点でエラーにする。"""


def _no_dup_mapping(loader, node, deep=False):
    keys = [k.value for k, _ in node.value]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise ValueError(f"config.yaml に同じキーが2回あります: {dup}（{node.start_mark.line + 1}行目の階層）")
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_NoDupLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dup_mapping)


def load_config() -> dict:
    _load_env()
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.load(f, Loader=_NoDupLoader)

    cfg["_app_id"] = os.environ.get("RAKUTEN_APP_ID", "").strip()
    cfg["_access_key"] = os.environ.get("RAKUTEN_ACCESS_KEY", "").strip()
    cfg["_affiliate_id"] = os.environ.get("RAKUTEN_AFFILIATE_ID", "").strip()
    cfg["_threads_token"] = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    cfg["_threads_user_id"] = os.environ.get("THREADS_USER_ID", "").strip()
    cfg["_instagram_token"] = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    cfg["_instagram_user_id"] = os.environ.get("INSTAGRAM_USER_ID", "").strip()

    for d in (DATA_DIR, DRAFTS_DIR, SESSION_DIR):
        d.mkdir(parents=True, exist_ok=True)
    _apply_post_boost(cfg)
    return cfg


def _apply_post_boost(cfg: dict) -> None:
    """期間限定でROOMの1日の投稿数を上乗せする（post_boost: {extra, until}）。
    2026-10-13: 削除ジョブの不具合で消えた投稿（約600件）を取り戻すため。until を過ぎると自動で元に戻る。"""
    import math
    from datetime import date
    b = cfg.get("post_boost") or {}
    extra = int(b.get("extra", 0) or 0)
    until = str(b.get("until") or "")
    if not extra or not until or date.today().isoformat() > until:
        return
    base = int(cfg.get("post_count", 10))
    cfg["post_count"] = base + extra
    cfg["candidate_pool"] = max(int(cfg.get("candidate_pool", 0) or 0), round(cfg["post_count"] * 1.6))
    runs = int((cfg.get("server", {}) or {}).get("room_post_runs_per_day", 8) or 8)
    cfg["post_batch_size"] = max(int(cfg.get("post_batch_size", 0) or 0), math.ceil(cfg["post_count"] / runs) + 2)


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
