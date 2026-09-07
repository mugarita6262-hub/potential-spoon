# 楽天ROOM 半自動投稿ツール

毎日、売れそうな楽天商品を選び、紹介文（キャプション）を生成し、楽天ROOMの投稿画面を
タブで開くツール。**各タブの「完了」クリックだけ人間が押す**半自動方式。
登録上限対策に、古い投稿を自動削除する機能つき。

> ⚠️ 楽天ROOMの規約は完全自動化ツールを禁止しています。本ツールは投稿の最終操作を
> 手動に残し、操作間隔を空け、件数を制限してリスクを抑えていますが、アカウント停止の
> 可能性はゼロではありません。自己責任で利用してください。

## セットアップ

### 1. 楽天ウェブサービスのアプリを作成
- https://webservice.rakuten.co.jp/ →「アプリID発行」
- 応募タイプ:「API/バックエンドサービス」→ 実行マシンのグローバルIPを登録
- APIスコープ:「楽天市場API」
- 発行される **アプリケーションID（UUID）** と **アクセスキー** を控える（2026年2月〜の新方式）

### 2. `.env` を用意
`.env.example` をコピーして記入:
- `RAKUTEN_APP_ID` … アプリケーションID（UUID）
- `RAKUTEN_ACCESS_KEY` … アクセスキー（秘密情報）
- `RAKUTEN_AFFILIATE_ID` … アフィリエイトID（任意）
- `ANTHROPIC_API_KEY` … Claude APIキー（任意。あればキャプションを自動生成。無ければ手動）

### 3. 依存関係
```
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
```

### 4. 初回ログイン（1回だけ）
楽天のログイン画面は自動操作を検知して固まるため、**ツール専用の Chrome プロファイル**
（`data/session/chrome_profile`）に CDP でつないで操作する。普段の Chrome とは別枠。

1. `login.bat` をダブルクリック
2. 開いた Chrome で楽天ROOMにログイン
3. 黒い画面で Enter → 「ログイン済みです」で完了
4. 以降ログイン不要（`post` や `prune` が「未ログイン」と言ったときだけ再実行）

## 毎日の使い方

| ダブルクリック | 中身 |
|---|---|
| **nightly.bat** | ① prune（古い投稿を削除して空きを作る）→ ② prepare（候補選定＋キャプション生成）→ ③ post（新規10件をタブで開く） |
| **post_now.bat** | ③のみ（新規10件をタブで開く） |
| **prune.bat** | 古い投稿をまとめて削除（`max_delete_per_run` 件） |
| **prune_preview.bat** | 削除せずに対象を確認 |
| **post_test.bat** | 投稿せずに1件ずつ流し込みを確認（ドライラン） |

`post` は新規10件ぶんの投稿モーダルを別タブで開き、コメントを自動入力する。
利用者は各タブの赤い「完了」ボタンを押し、最後にコンソールで Enter。

## 設定（config.yaml）

- `post_count` … 実際に新規投稿する件数（既存とかぶった分は次の候補で埋める）
- `candidate_pool` … 選定してキャプションを用意する候補数（かぶり吸収用バッファ）
- `sources.ranking.genre_ids` … 候補を集める楽天ランキングのジャンル
- `scoring.weights` … レビュー数・評価・順位・価格帯・ポイント倍率の重み
- `prune.mode` … `oldest`（先頭から）または `soldout`（売切れのみ）
- `prune.only_before` … この日付より後の投稿は削除しない安全ガード
- `prune.max_delete_per_run` … 1回の削除上限

## しくみ（要点）

- 商品情報: 楽天商品検索/ランキングAPI（`openapi.rakuten.co.jp`、accessKey ヘッダー認証）
- 投稿: `room.rakuten.co.jp/mix?itemcode=<ショップ:商品ID>` のモーダル（`#collect-content` にコメント、`button.collect-btn`「完了」）
- 削除: 投稿詳細ページの `button[aria-label="削除"]` → `confirm()` を自動承認
- ブラウザ: 実 Chrome を `--remote-debugging-port=9222` で起動し Playwright が `connect_over_cdp`

## トラブル時

- prune が「一覧を開けませんでした」→ `data/prune_fail.txt` / `.png` を確認。連続操作の一時制限なら時間をあけて再実行
- 投稿モーダルが開かない/入力されない → 楽天ROOMの画面変更の可能性。`src/poster.py` のセレクタを調整
- `explore.py` … ROOMのDOM構造を調べる調査用スクリプト
