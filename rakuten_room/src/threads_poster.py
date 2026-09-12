"""Threads（Meta公式API）への投稿。完全自動（人の最終クリック無し）。

事前準備は SETUP_THREADS.md 参照。.env に THREADS_ACCESS_TOKEN / THREADS_USER_ID が必要。
ROOMと違い公式APIでの投稿なのでプラットフォーム規約上の問題は無い。
"""
from __future__ import annotations

import time

import requests

API_BASE = "https://graph.threads.net/v1.0"


def _is_transient(resp: requests.Response) -> bool:
    if resp.status_code >= 500:
        return True
    try:
        return bool(resp.json().get("error", {}).get("is_transient"))
    except ValueError:
        return False


def _post_with_retry(url: str, data: dict, retries: int = 2, backoff: float = 5.0):
    """Meta側の一時的なエラー（is_transient / 5xx）は少し待って自動リトライする。"""
    last = None
    for attempt in range(retries + 1):
        resp = requests.post(url, data=data, timeout=20)
        if resp.ok:
            return resp
        last = resp
        if attempt < retries and _is_transient(resp):
            time.sleep(backoff * (attempt + 1))
            continue
        break
    return last


def post_to_threads(access_token: str, user_id: str, text: str,
                     image_url: str | None = None) -> str:
    """投稿を作成して公開し、投稿IDを返す（2段階: 作成→公開、Meta公式の手順）。"""
    if not access_token or not user_id:
        raise RuntimeError(
            ".env の THREADS_ACCESS_TOKEN / THREADS_USER_ID が未設定です。"
            "SETUP_THREADS.md の手順で取得してください。"
        )

    create_params = {"text": text[:500], "access_token": access_token}
    if image_url:
        create_params["media_type"] = "IMAGE"
        create_params["image_url"] = image_url
    else:
        create_params["media_type"] = "TEXT"

    resp = _post_with_retry(f"{API_BASE}/{user_id}/threads", create_params)
    if not resp.ok:
        raise RuntimeError(f"投稿の作成に失敗しました: {resp.status_code} {resp.text}")
    creation_id = resp.json().get("id")
    if not creation_id:
        raise RuntimeError(f"投稿の作成に失敗しました（idなし）: {resp.text}")

    # Meta推奨: publish前にコンテナ処理の反映を少し待つ
    time.sleep(5)

    pub = _post_with_retry(
        f"{API_BASE}/{user_id}/threads_publish",
        {"creation_id": creation_id, "access_token": access_token},
    )
    if not pub.ok:
        raise RuntimeError(f"投稿の公開に失敗しました: {pub.status_code} {pub.text}")
    post_id = pub.json().get("id")
    if not post_id:
        raise RuntimeError(f"投稿の公開に失敗しました（idなし）: {pub.text}")
    return post_id


def refresh_long_lived_token(access_token: str) -> dict:
    """長期トークンを延長する（有効期限60日、24時間以上経過していればいつでも延長可）。

    {"access_token": 新トークン, "expires_in": 秒数} を返す。失敗時は例外。
    """
    resp = requests.get(
        f"{API_BASE}/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": access_token},
        timeout=20,
    )
    if not resp.ok:
        raise RuntimeError(f"トークン延長に失敗しました: {resp.status_code} {resp.text}")
    data = resp.json()
    if not data.get("access_token"):
        raise RuntimeError(f"トークン延長に失敗しました（access_tokenなし）: {resp.text}")
    return data
