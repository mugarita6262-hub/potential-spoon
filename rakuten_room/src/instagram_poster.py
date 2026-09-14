"""Instagram（Instagram API with Instagram Login）への投稿。完全自動。

ThreadsのAPIと同じ「コンテナ作成→公開」の2段階方式。ただしInstagramのフィード投稿は
画像必須（テキストのみ投稿は不可）で、キャプション内のリンクはクリックできない
（プロフィール欄のリンク1つだけがクリック可能）という制約が大きく異なる点。
"""
from __future__ import annotations

import time

import requests

API_BASE = "https://graph.instagram.com/v23.0"


def _is_transient(resp: requests.Response) -> bool:
    if resp.status_code >= 500:
        return True
    try:
        return bool(resp.json().get("error", {}).get("is_transient"))
    except ValueError:
        return False


def _post_with_retry(url: str, data: dict, retries: int = 2, backoff: float = 5.0):
    last = None
    for attempt in range(retries + 1):
        resp = requests.post(url, data=data, timeout=30)
        if resp.ok:
            return resp
        last = resp
        if attempt < retries and _is_transient(resp):
            time.sleep(backoff * (attempt + 1))
            continue
        break
    return last


def post_to_instagram(access_token: str, user_id: str, image_url: str, caption: str) -> str:
    """画像投稿を作成して公開し、投稿IDを返す。画像は必須（テキストのみ不可）。"""
    if not access_token or not user_id:
        raise RuntimeError(
            ".env の INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID が未設定です。"
        )
    if not image_url:
        raise RuntimeError("Instagramのフィード投稿には画像URLが必須です。")

    create_params = {
        "image_url": image_url,
        "caption": caption[:2200],
        "access_token": access_token,
    }
    resp = _post_with_retry(f"{API_BASE}/{user_id}/media", create_params)
    if not resp.ok:
        raise RuntimeError(f"投稿の作成に失敗しました: {resp.status_code} {resp.text}")
    creation_id = resp.json().get("id")
    if not creation_id:
        raise RuntimeError(f"投稿の作成に失敗しました（idなし）: {resp.text}")

    # Meta推奨: publish前にコンテナ処理の反映を少し待つ（画像ダウンロード等があるためThreadsより長め）
    time.sleep(8)

    pub = _post_with_retry(
        f"{API_BASE}/{user_id}/media_publish",
        {"creation_id": creation_id, "access_token": access_token},
    )
    if not pub.ok:
        raise RuntimeError(f"投稿の公開に失敗しました: {pub.status_code} {pub.text}")
    post_id = pub.json().get("id")
    if not post_id:
        raise RuntimeError(f"投稿の公開に失敗しました（idなし）: {pub.text}")
    return post_id


def refresh_long_lived_token(access_token: str) -> dict:
    """長期トークンを延長する（有効期限60日）。{"access_token":..., "expires_in":...} を返す。

    Threadsのth_refresh_tokenと同じ方式で、app secretは不要（トークン自体だけで延長できる）。
    """
    resp = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": access_token},
        timeout=20,
    )
    if not resp.ok:
        raise RuntimeError(f"トークン延長に失敗しました: {resp.status_code} {resp.text}")
    data = resp.json()
    if not data.get("access_token"):
        raise RuntimeError(f"トークン延長に失敗しました（access_tokenなし）: {resp.text}")
    return data
