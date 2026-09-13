"""「おまかせ」実行時に、サーバー側の状態をローカルへ自動で取り込む（任意機能）。

.env の GCLOUD_INSTANCE / GCLOUD_ZONE が設定されていれば、おまかせの最初に
サーバーのconfig.yaml（自動昇格されたジャンル）とdocs/A8アフィリリンク取得依頼.md
（自動追記された依頼）を確認し、差分があればローカルに取り込む。
サーバー未設定・オフライン・gcloud未インストール等の場合は、何もせず静かにスキップする
（サーバーを使わないローカル運用の人に影響しないようにするため）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from .config import ROOT

CONFIG_PATH = ROOT / "config.yaml"
A8_REQUEST_LOCAL_COPY = ROOT / "docs" / "A8アフィリリンク取得依頼_サーバー最新版.md"
REMOTE_ROOT = "/home/kirui/rakuten_room"


def _gcloud_path() -> str | None:
    return shutil.which("gcloud") or shutil.which("gcloud.cmd")


def _scp_from_server(remote_path: str, local_path: Path, gcloud: str,
                      instance: str, zone: str) -> bool:
    try:
        subprocess.run(
            [gcloud, "compute", "scp", f"{instance}:{remote_path}", str(local_path),
             "--zone", zone],
            check=True, capture_output=True, timeout=60,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def _scp_to_server(local_path: Path, remote_path: str, gcloud: str,
                    instance: str, zone: str) -> bool:
    try:
        subprocess.run(
            [gcloud, "compute", "scp", str(local_path), f"{instance}:{remote_path}",
             "--zone", zone],
            check=True, capture_output=True, timeout=60,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def _merge_genre_ids(server_cfg_path: Path) -> list[int]:
    """サーバーのconfig.yamlにだけあるジャンルIDを、ローカルのconfig.yamlに追加する。
    他のローカル個人設定（post_countなど）は一切変更しない。
    """
    local_cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    server_cfg = yaml.safe_load(server_cfg_path.read_text(encoding="utf-8"))

    local_ids = set(local_cfg["sources"]["ranking"]["genre_ids"])
    server_ids = set(server_cfg["sources"]["ranking"]["genre_ids"])
    new_ids = sorted(server_ids - local_ids)
    if not new_ids:
        return []

    local_cfg["sources"]["ranking"]["genre_ids"] = sorted(local_ids | server_ids)
    header = (
        "# 楽天ROOM 投稿ツール 設定\n"
        "# 主な項目は GUI の『⚙ 設定』から変更できます（このファイルを直接編集する必要はありません）\n"
        "# scoring / per_genre / favorites などの詳細はここで調整します\n\n"
    )
    CONFIG_PATH.write_text(
        header + yaml.safe_dump(local_cfg, allow_unicode=True, sort_keys=False,
                                 default_flow_style=False),
        encoding="utf-8",
    )
    return new_ids


def sync_with_server() -> None:
    """おまかせの最初に呼ぶ。サーバー未設定なら即座に何もせず戻る。"""
    instance = os.environ.get("GCLOUD_INSTANCE", "").strip()
    zone = os.environ.get("GCLOUD_ZONE", "").strip()
    if not instance or not zone:
        return
    gcloud = _gcloud_path()
    if not gcloud:
        return

    print("サーバーとの差分を確認しています…")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_cfg = Path(tmp) / "server_config.yaml"
        if _scp_from_server(f"{REMOTE_ROOT}/config.yaml", tmp_cfg, gcloud, instance, zone):
            try:
                new_ids = _merge_genre_ids(tmp_cfg)
                if new_ids:
                    print(f"  🎯 サーバーで自動昇格したジャンルを取り込みました: {new_ids}")
                else:
                    print("  ジャンルの差分はありません。")
            except Exception as exc:  # noqa: BLE001
                print(f"  サーバー設定の取り込みに失敗（無視して続行）: {exc}")
        else:
            print("  サーバーに接続できませんでした（オフライン等。無視して続行）。")

        tmp_doc = Path(tmp) / "a8_request.md"
        if _scp_from_server(f"{REMOTE_ROOT}/docs/A8アフィリリンク取得依頼.md",
                             tmp_doc, gcloud, instance, zone) and tmp_doc.exists():
            A8_REQUEST_LOCAL_COPY.parent.mkdir(parents=True, exist_ok=True)
            A8_REQUEST_LOCAL_COPY.write_bytes(tmp_doc.read_bytes())
            print(f"  A8追加依頼の最新版を取得しました: {A8_REQUEST_LOCAL_COPY.name}"
                  "（新しいセクションがあれば本体ファイルに手動でコピーしてください）")

    # ローカルで編集したA8リンクをサーバーに反映（サーバーのa8ローテーションを最新に保つ）
    local_links = ROOT / "data" / "a8_links.yaml"
    if local_links.exists():
        _scp_to_server(local_links, f"{REMOTE_ROOT}/data/a8_links.yaml", gcloud, instance, zone)
