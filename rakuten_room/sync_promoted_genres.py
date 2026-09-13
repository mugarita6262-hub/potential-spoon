"""サーバーが自動昇格させたジャンルを、ローカルのconfig.yamlにも取り込む。

sources.ranking.genre_ids だけをマージする（他の設定はローカルの値を尊重し、
post_count や engage 等の個人設定を上書きしない）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

LOCAL_CONFIG = Path(__file__).resolve().parent / "config.yaml"


def main() -> int:
    if len(sys.argv) != 2:
        print("使い方: python sync_promoted_genres.py <サーバーから取得したconfig.yamlのパス>")
        return 1
    server_copy = Path(sys.argv[1])

    local_cfg = yaml.safe_load(LOCAL_CONFIG.read_text(encoding="utf-8"))
    server_cfg = yaml.safe_load(server_copy.read_text(encoding="utf-8"))

    local_ids = set(local_cfg["sources"]["ranking"]["genre_ids"])
    server_ids = set(server_cfg["sources"]["ranking"]["genre_ids"])
    new_ids = server_ids - local_ids

    if not new_ids:
        print("新しく昇格したジャンルはありません。")
        return 0

    local_cfg["sources"]["ranking"]["genre_ids"] = sorted(local_ids | server_ids)
    header = (
        "# 楽天ROOM 投稿ツール 設定\n"
        "# 主な項目は GUI の『⚙ 設定』から変更できます（このファイルを直接編集する必要はありません）\n"
        "# scoring / per_genre / favorites などの詳細はここで調整します\n\n"
    )
    LOCAL_CONFIG.write_text(
        header + yaml.safe_dump(local_cfg, allow_unicode=True, sort_keys=False,
                                 default_flow_style=False),
        encoding="utf-8",
    )
    print(f"ローカルのconfig.yamlに新しいジャンルを追加しました: {sorted(new_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
