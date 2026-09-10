# 楽天ROOM 半自動投稿ツール

売れ筋の楽天商品を選び、紹介文を生成し、楽天ROOMの投稿画面をタブで開くツール。
**各タブの「完了」クリックだけ人間が押す**半自動方式。登録上限対策の古い投稿の自動削除つき。

> ⚠️ 楽天ROOMの規約は完全自動化ツールを禁止しています。本ツールは投稿の最終操作を
> 手動に残し、操作間隔を空け、件数を制限してリスクを抑えていますが、アカウント停止の
> 可能性はゼロではありません。自己責任で利用してください。

## 使い方（GUI）

**`rakuten_room.bat` をダブルクリック** すると操作ウィンドウが開きます。

| ボタン | 何をする |
|---|---|
| 初回ログイン | 最初の1回だけ。開いた Chrome で楽天ROOMにログイン → 下の欄で送信(Enter) |
| ① 今日の準備 | 商品を選定し、紹介文を自動生成（セール日は投稿目標を増やす） |
| ② 投稿する | 新規◯件ぶんのタブを開く。各タブで赤い「完了」を押し、下の欄で送信(Enter) |
| 古い投稿を削除 | 「削除件数」の分だけ古い投稿を削除（空き確保） |
| 削除プレビュー | 削除せずに対象だけ確認 |
| 今日の状況を見る | 目標数・投稿済み数・セール判定を表示 |
| 設定ファイルを開く | config.yaml をエディタで開く |

- 黒いログが「Enter待ち」で止まったら、下の入力欄で **送信(Enter)** を押す。
- 「② 投稿する」は `post_batch_size` 件ずつ。朝・昼・夜に分けて押すとピーク時間帯に分散できる。

## セットアップ（初回のみ）

1. **楽天ウェブサービスのアプリ**を作成（https://webservice.rakuten.co.jp/）
   - 応募タイプ「API/バックエンドサービス」、実行マシンのグローバルIPを登録、スコープ「楽天市場API」
   - **アプリケーションID（UUID）** と **アクセスキー** を控える
2. `.env.example` を `.env` にコピーして記入
   - `RAKUTEN_APP_ID` / `RAKUTEN_ACCESS_KEY` / `RAKUTEN_AFFILIATE_ID`（任意）
   - `ANTHROPIC_API_KEY`（任意。あれば紹介文を自動生成。無ければ手動ペースト方式）
3. 依存関係
   ```
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   .venv\Scripts\python.exe -m playwright install chromium
   ```
4. GUI の「初回ログイン」

## 設定（config.yaml）

- `post_count` … 1日に新規投稿する件数
- `post_batch_size` … 「② 投稿する」1回で開くタブ数（分散投稿）
- `candidate_pool` … 候補として選ぶ件数（かぶり吸収バッファ）
- `sale_boost` … 5と0の日/スーパーSALE/マラソンの投稿増量倍率。`manual_events` に期間を書くと確実
- `sources.ranking.genre_ids` … 候補を集める楽天ランキングのジャンル
- `scoring.weights` … レビュー数・評価・順位・価格帯・ポイント倍率の重み
- `prune.only_before` … この日付より後の投稿は削除しない安全ガード
- `prune.max_delete_per_run` … 「古い投稿を削除」の既定件数

## しくみ（要点）

- 商品情報: 楽天商品検索/ランキングAPI（`openapi.rakuten.co.jp`、accessKey ヘッダー認証）
- 投稿: `room.rakuten.co.jp/mix?itemcode=<ショップ:商品ID>` のモーダル（`#collect-content` にコメント、`button.collect-btn`「完了」）
- 削除: `/items?unavailable_item=1` の一覧 → 投稿詳細の `button[aria-label="削除"]` → `confirm()` 自動承認
- ブラウザ: ツール専用プロファイルの実 Chrome を `--remote-debugging-port=9222` で起動し Playwright が `connect_over_cdp`
- CLI 直叩きも可: `.venv\Scripts\python.exe -m src.main {login|status|prepare|post|prune}`（`prune --commit --max N`）

## トラブル時

- 削除が「一覧を開けませんでした」→ 時間をあけて再実行（連続操作の一時制限）
- 投稿モーダルが開かない/入力されない → 楽天ROOMの画面変更の可能性。`src/poster.py` のセレクタを調整
