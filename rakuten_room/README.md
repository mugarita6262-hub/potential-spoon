# 楽天ROOM 半自動投稿ツール ＋ Threads自動拡散

売れ筋の楽天商品を選び、紹介文を生成し、楽天ROOMの投稿画面をタブで開くツール。
**各タブの「完了」クリックだけ人間が押す**半自動方式。登録上限対策の古い投稿の自動削除つき。

さらに、楽天の値下がり品・過去最安値検知とA8アフィリリンクを、**Threads（`aki.h190`アカウント）へ
公式APIで完全自動投稿**する仕組みも同梱（こちらはROOMと違い最終クリック不要）。

> ⚠️ 楽天ROOMの規約は完全自動化ツールを禁止しています。本ツールは投稿の最終操作を
> 手動に残し、操作間隔を空け、件数を制限してリスクを抑えていますが、アカウント停止の
> 可能性はゼロではありません。自己責任で利用してください。
>
> ⚠️ Threadsのいいね・フォロー・コメントを他人の投稿に対して自動化することはできません
> （公式APIが対応していない上、Metaのbot検知は厳しく凍結リスクが高いため意図的に作っていません）。

## 毎日の運用フロー（結論）

**`rakuten_room.bat` を開いて「▶ おまかせ」を1日1回押すだけ。** 中で以下が順番に自動実行される：

1. ROOMへの新規投稿（タブが開くので、各タブの赤い「完了」だけ手動で押す）
2. いいね回り／フォロー回り（ROOM内、慎重な半自動）
3. （設定していれば）古い投稿の削除
4. 楽天の値下がり・過去最安値品をThreadsへ自動投稿（`sns`、完全自動・操作不要）
5. A8アフィリリンクをローテーションでThreadsへ自動投稿（`a8`、完全自動・操作不要）

手を動かすのは1と2の一部だけで、4と5は裏で勝手に終わっている。

**週1回くらいの頻度**で、Threadsの反応を見る：
```
.venv\Scripts\python.exe -m src.main insights
```
ジャンル・商品別の平均いいね数がランキング表示される。反応が良いジャンルが見つかったら、
そのジャンルでA8の新規プログラムを探して追加する（`docs/`にコワーカー依頼テンプレあり）。

## サーバー運用（任意）

1日中ノーリスクな調査（価格収集・反応集計）を回しつつ、Claude課金が発生する投稿系は
今までと同じ頻度に抑えたい場合、`prepare`/`sns`/`a8`/`insights`/`collect` はサーバーに
出せる（**ROOMの`post`/`like`/`follow`/`prune`は実Chrome必須なのでローカルのまま**）。

### 全体像
```
[サーバー]  collect（調査・無料・高頻度） ─┐
            insights（反応集計・無料・高頻度）├─ data/ フォルダに書き込む
            prepare（ROOM準備・Claude課金・1日1回）─┘
            sns / a8（Threads投稿・Claude課金・既存頻度）
                          │
                 Dropbox/OneDrive等で同期
                          │
[ローカルPC]  data/ フォルダを見て、GUIで「投稿する」「いいね回り」等を実行
```
`data/`フォルダ（`drafts/`・`price_history.json`・`a8_links.yaml`等）と`.env`を、
サーバーとローカル両方からアクセスできるクラウド同期フォルダ（Dropbox/OneDrive等）に
置く。サーバーの`prepare`が書いた下書き・キャプションがローカルに届けば、GUIは今まで
通り「準備済み」を検知して「投稿する」が押せる（追加の実装は不要）。
`data/session/`（Chromeログインセッション）は同期対象から外してよい（ローカル専用）。

### コスト
Claude APIは`prepare`/`sns`/`a8`（＝実際に投稿する時）だけで使う。`collect`/`insights`は
楽天API・Threads APIへの素の問い合わせのみでClaude不使用＝実質無料。目安：

| 処理 | 頻度 | 1回のコスト |
|---|---|---|
| `collect` / `insights` | 何回でも | $0 |
| ROOM `prepare`（約40件） | 1日1回 | 約$0.005 |
| Threads `sns`（最大3件） | 1日数回（該当があった時のみ課金） | 約$0.003 |
| Threads `a8`（1件） | 1日1回 | 約$0.001 |

**合計で1日1〜2円、月30〜60円程度**。サーバー代（月額500〜1000円程度の小規模VPSで十分）
の方が支配的なコスト。

### セットアップ
1. サーバーにこのリポジトリを配置し、`.env`に`RAKUTEN_*` / `ANTHROPIC_API_KEY` /
   `THREADS_ACCESS_TOKEN` / `THREADS_USER_ID` を設定（ローカルと同じ値でOK）
2. `.env`に`WEBAPP_USER` / `WEBAPP_PASSWORD`（ダッシュボードの認証、必須） / `WEBAPP_PORT`（既定8080）を追加
3. 依存関係インストール後、起動：
   ```
   .venv/bin/python -m src.webapp
   ```
4. ブラウザで `http://サーバーのIP:8080/` を開き、Basic認証でログイン
5. **必ずHTTPS化する**（Basic認証は平文同然のため）。手軽なのは
   [Caddy](https://caddyserver.com/) を前段に置く方法（自動でLet's Encrypt証明書を取得）：
   ```
   your-domain.example.com {
       reverse_proxy localhost:8080
   }
   ```
6. `config.yaml`の`server:`セクションで、各ジョブを1日に何回・何時〜何時の間で実行するか調整
7. 常駐させるには`systemd`（Linux）等でサービス化し、再起動時も自動起動するようにする

### ダッシュボードでできること
- `collect`/`insights`/`prepare`/`sns`/`a8`の手動実行ボタン
- 直近の実行結果・ログ表示
- 裏側のスケジューラが`config.yaml`の`server:`設定に従い、1日の中でランダムな時刻に
  自動実行し続ける（人間がクリックする必要は無い）

## 使い方（GUI）

**`rakuten_room.bat` をダブルクリック** すると操作ウィンドウが開きます。

| ボタン | 何をする |
|---|---|
| 初回ログイン | 最初の1回だけ。開いた Chrome で楽天ROOMにログイン → 下の欄で送信(Enter) |
| ▶ おまかせ | 上記フローを一括実行（ROOM投稿→いいね→フォロー→削除→Threads2種） |
| 投稿だけ | ROOMへの投稿のみ実行 |
| ♡ いいね回り／＋ フォロー回り／フォロー整理 | ROOM内のエンゲージメント個別実行 |
| 🗑 古い投稿を削除 | 「削除件数」の分だけ古い投稿を削除（空き確保） |
| 📈 値下がり品をThreadsへ | `sns` を単独実行（値下がり・過去最安値検知→Threads投稿） |
| ⚙ 設定 | config.yaml の主要項目をGUIで編集 |

- 黒いログが「Enter待ち」で止まったら、下の入力欄で **送信(Enter)** を押す。

## CLIコマンド一覧

GUIを使わず直接実行する場合（`.venv\Scripts\python.exe -m src.main <コマンド>`）:

| コマンド | 内容 |
|---|---|
| `login` | 初回だけ。ブラウザで楽天ROOMに手動ログイン |
| `prepare` | 商品を選定してキャプションを生成 |
| `post` | 投稿画面に流し込む（最後は手動） |
| `run` | prepare→post |
| `like` / `follow` / `unfollow` | ROOM内エンゲージメント（`--n N`で件数指定） |
| `prune` | 古い投稿の削除（`--commit --max N`） |
| **`sns`** | 楽天の値下がり・過去最安値をThreadsに自動投稿 |
| **`a8`** | A8アフィリリンクをローテーションでThreadsに自動投稿 |
| **`collect`** | 調査専用。広いジャンルの価格スナップショットだけ集める（Claude不使用・実質無料） |
| **`insights`** | Threads投稿の反応をジャンル・商品別に集計して表示 |
| `daily` | 上記フロー1〜5を一括実行（GUIの「おまかせ」と同じ） |

## セットアップ（初回のみ）

### 楽天ROOM側
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

### Threads側
[SETUP_THREADS.md](SETUP_THREADS.md) の手順でMetaアプリを作成し、`.env` に
`THREADS_ACCESS_TOKEN` / `THREADS_USER_ID` を設定する（アクセストークンは`sns`/`a8`/`daily`
実行のたびに自動延長されるので、一度設定すれば以降は放置でOK）。

### A8アフィリリンク側
`data/a8_links.yaml`（`data/a8_links.example.yaml`がひな形）に、投稿したいA8のアフィリリンクを
登録する。リンクの発行を他の人に頼む場合は `docs/A8アフィリリンク取得依頼.md` のテンプレを使う。

## 設定（config.yaml）

**ROOM側**
- `post_count` … 1日に新規投稿する件数
- `post_batch_size` … 「投稿する」1回で開くタブ数（分散投稿）
- `candidate_pool` … 候補として選ぶ件数（かぶり吸収バッファ）
- `sale_boost` … 5と0の日/スーパーSALE/マラソンの投稿増量倍率。`manual_events` に期間を書くと確実
- `sources.ranking.genre_ids` … 候補を集める楽天ランキングのジャンル
- `scoring.weights` … レビュー数・評価・順位・価格帯・ポイント倍率の重み
- `prune.only_before` … この日付より後の投稿は削除しない安全ガード
- `prune.max_delete_per_run` … 「古い投稿を削除」の既定件数
- `engage.daily_likes` / `daily_follows` / `daily_prune` … 「おまかせ」1回分の件数

**Threads側**
- `sns.enabled` / `sns.run_in_daily` … 値下がり検知投稿の有効化／おまかせへの組み込み
- `sns.lookback_days` / `sns.min_discount_pct` … 値下がり判定の基準
- `sns.repost_cooldown_days` … 同じ商品を再投稿するまでの間隔
- `sns.threads.post_count` … 1回に投稿する件数
- `a8.enabled` / `a8.run_in_daily` … A8ローテーション投稿の有効化／おまかせへの組み込み
- `a8.repost_cooldown_days` … 同じA8リンクを再投稿するまでの間隔
- `sns.threads.disclosure` / `a8.disclosure` … PR表記（景品表示法対応。削除しないこと）
- `research.extra_genre_ids` … `collect`で価格収集する追加ジャンル（投稿対象には影響しない）
- `server.*_window` / `server.*_runs_per_day` … サーバー常駐時、各ジョブを1日に何回・何時台に自動実行するか

## しくみ（要点）

**ROOM投稿**
- 商品情報: 楽天商品検索/ランキングAPI（`openapi.rakuten.co.jp`、accessKey ヘッダー認証）
- 投稿: `room.rakuten.co.jp/mix?itemcode=<ショップ:商品ID>` のモーダル（`#collect-content` にコメント、`button.collect-btn`「完了」）
- 削除: `/items?unavailable_item=1` の一覧 → 投稿詳細の `button[aria-label="削除"]` → `confirm()` 自動承認
- ブラウザ: ツール専用プロファイルの実 Chrome を `--remote-debugging-port=9222` で起動し Playwright が `connect_over_cdp`

**Threads投稿**
- `price_history.py` が候補商品の価格を毎日スナップショットし、値下がり率・過去最安値を判定
- `sns_captions.py` / `a8_captions.py` がClaudeで告知文生成（PR表記はコード側で必ず付与）
- `threads_poster.py` がThreads公式APIで投稿（作成→公開の2段階、5xx/一時エラーは自動リトライ）
- `insights.py` が投稿から24時間以上経ったものの反応を取得し、ジャンル・商品別に集計

## トラブル時

- 削除が「一覧を開けませんでした」→ 時間をあけて再実行（連続操作の一時制限）
- 投稿モーダルが開かない/入力されない → 楽天ROOMの画面変更の可能性。`src/poster.py` のセレクタを調整
- `sns`/`a8`が「未設定です」で止まる → `.env`のTHREADS_ACCESS_TOKEN/THREADS_USER_IDを確認（[SETUP_THREADS.md](SETUP_THREADS.md)参照）
- Threadsトークンが60日以上前に取得したまま一度も`sns`/`a8`/`daily`を実行していない → 失効しているので[SETUP_THREADS.md](SETUP_THREADS.md)の手順3〜5をやり直す
