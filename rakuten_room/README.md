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

## 役割分担（サーバー ⇔ デスクトップ）

Threads側（ブラウザ不要・API呼び出しのみ）は**サーバーに常駐**させ、ROOM側（実Chrome＋
ログイン済みセッション必須）は**ローカルPCのまま**、という分担で運用している。

| | サーバー（GCP VM等） | デスクトップ（ローカルPC） |
|---|---|---|
| 対象 | Threads関連 | ROOM関連 |
| コマンド | `collect`／`insights`／`sns`／`a8` | `prepare`／`post`／`like`／`follow`／`prune` |
| 実行方法 | `src/webapp.py`のスケジューラが1日中自動実行 | GUIの「▶おまかせ」を1日1回手動で押す |
| 人の操作 | 無し | 投稿タブの「完了」クリックだけ |

**注意**: サーバー運用にする場合、ローカルの`config.yaml`は`sns.run_in_daily` /
`a8.run_in_daily`を**`false`**にしておくこと（`true`のままだと、ローカルの「おまかせ」でも
サーバーとは別にThreads投稿が走り、二重投稿の原因になる）。サーバーを使わずローカルだけで
完結させたい場合は、逆にこの2つを`true`に戻せば従来通り動く。

## 1日の流れ

**サーバー側（つけっぱなし、常に自動・完全無人）**
```
06:00〜23:00の間でランダムに:
  collect   × 12回（価格調査、無料）
  insights  × 6回（反応集計、無料）
  sns       × 3回（値下がり品をThreads投稿）
  a8        × 1回（A8リンクをThreads投稿）
```

**ローカルPC側（PCを開いた時、1日1回）**
```
rakuten_room.bat →「▶ おまかせ」
  → ROOM投稿タブが開く → 各タブの「完了」を押す
  → いいね回り・フォロー回り（自動）
  → （設定していれば）古い投稿の削除
```
人の作業はここだけ。

## 調査→施策のループ（自動判定つき）

「反応データを自分で解釈して判断する」手間をなくすため、insightsの後に`src/optimizer.py`が
自動でアクションを判定する。人がやる部分は最小限に絞ってある。

```
① サーバーが collect で日々の価格データを蓄積
      （sources.ranking.genre_ids ＋ research.extra_genre_ids ＝ 計15ジャンル）
② sns/a8 が投稿し、insights がThreadsの反応（いいね・閲覧数）を記録
③ insights 実行のたびに、自動で判定される（人の判断は無し）:

   【楽天ジャンルが好調】→ 自動昇格
      research.extra_genre_ids（調査専用）にあったジャンルの平均いいね数が
      全体平均の1.3倍以上なら、サーバーの config.yaml を書き換えて
      sources.ranking.genre_ids（投稿候補ジャンル）に自動追加する
      → 同じサーバーで動く sns は次回実行から即座にこの新ジャンルも対象にする
      → ntfy でスマホに通知が届く

   【A8ジャンル（genreタグ）が好調】→ 依頼を自動追記
      自動申請はできないので、代わりに docs/A8アフィリリンク取得依頼.md
      （サーバー上のコピー）に「このジャンルの新規プログラムを探してください」
      という依頼セクションを自動で追記する
      → ntfy でスマホに通知が届く

④ 人がやる作業は「▶ おまかせ」を押すだけ
      GUIの「▶ おまかせ」（`daily`コマンド）を実行すると、投稿処理の前に
      自動でサーバーとの差分を確認し、以下を裏で済ませる（`.env`に
      `GCLOUD_INSTANCE`/`GCLOUD_ZONE`を設定していれば。未設定なら何もせずスキップ）：
      1. 自動昇格されたジャンルをローカルの config.yaml に取り込む
         （ROOMの prepare もこのジャンルを候補にするようになる）
      2. A8追加依頼の最新版を「docs/A8アフィリリンク取得依頼_サーバー最新版.md」として取得
         → 新しいセクションがあれば、コワーカーに渡している本体ファイルに手動でコピー
           （本体はコワーカー記入済みなので自動上書きしない設計）
      3. ローカルの data/a8_links.yaml をサーバーに反映
      ntfy通知は「今何が起きたか」を知るための補助（無くても動く）

⑤-B【A8の新規プログラムを実際に見つけて追加する（コワーカー or 自分）】
      1. A8.net → 「プログラム検索」で依頼された通りのジャンルをキーワード検索
      2. 気になるプログラムに「提携申請する」（即時 or 審査、数日かかることも）
      3. 提携後、プログラム詳細ページでテキストリンク素材を選び、アフィリリンクを発行
      4. docs/A8アフィリリンク取得依頼.md の表に記入
      5. その内容を data/a8_links.yaml に1エントリ追記
         （program_id / program_name / advertiser / note / url / genre）
      6. すぐ反映したい場合は sync_a8_links.bat をダブルクリック
         （急がなければ、次回「おまかせ」実行時に自動で反映される）

⑥ 次回の a8 実行から、新しいリンクも自動でローテーション対象に入る
```

### 通知の設定（ntfy.sh、任意だが推奨）
アカウント登録不要・無料。自動昇格やA8依頼追記が起きた時にスマホへ通知する。
1. スマホに「ntfy」アプリを入れる（iOS/Android）
2. 好きなトピック名を決める（他人と被らないよう、ランダムな文字列を混ぜる）
3. アプリでそのトピック名を購読
4. `.env`（サーバー側）に `NTFY_TOPIC=決めたトピック名` を設定

## サーバー運用

Claude課金が発生する投稿系（`prepare`/`sns`/`a8`）の頻度は今までと変えず、ノーリスクな
調査（`collect`/`insights`）だけ好きなだけ回したい場合、サーバーに常駐させる。
**ROOMの`post`/`like`/`follow`/`prune`は実Chrome必須なのでローカルのまま**。

### コスト
Claude APIは`sns`/`a8`（＝実際に投稿する時。`prepare`はローカルのROOM準備でも使用）だけで
使う。`collect`/`insights`は楽天API・Threads APIへの素の問い合わせのみでClaude不使用＝
実質無料。目安：

| 処理 | 頻度 | 1回のコスト |
|---|---|---|
| `collect` / `insights`（サーバー） | 何回でも | $0 |
| ROOM `prepare`（約40件・ローカル） | 1日1回 | 約$0.005 |
| Threads `sns`（最大3件・サーバー） | 1日数回（該当があった時のみ課金） | 約$0.003 |
| Threads `a8`（1件・サーバー） | 1日1回 | 約$0.001 |

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
8. ローカルの`config.yaml`は`sns.run_in_daily` / `a8.run_in_daily`を`false`にしておく
   （サーバーと二重投稿しないため。上の「役割分担」参照）
9. 楽天ウェブサービスのアプリ設定で、サーバーのIP（固定IP推奨）を
   「許可されたIPアドレス」に追加する（ローカルPCのIPと併記可）。忘れると楽天APIが403で失敗する
10. **ローカルPC**に`gcloud` CLIを入れて認証しておく（`gcloud auth login`）。
    ローカルの`.env`に`GCLOUD_INSTANCE`（インスタンス名）/ `GCLOUD_ZONE`（ゾーン）を設定すると、
    「おまかせ」実行時に自動でサーバーとの差分同期が走るようになる（上の「調査→施策のループ」参照）

### ダッシュボードでできること
- `collect`/`insights`/`sns`/`a8`の手動実行ボタン（`prepare`もコード上は呼べるが、
  下書き・キャプションをローカルに渡す同期の仕組みが無いため既定で無効`server.prepare_runs_per_day: 0`）
- 直近の実行結果・ログ表示
- 裏側のスケジューラが`config.yaml`の`server:`設定に従い、1日の中でランダムな時刻に
  自動実行し続ける（人間がクリックする必要は無い）

### 運用メモ
- **VMのタイムゾーンをAsia/Tokyoに設定しておく**（既定だとUTCのことが多く、`server:`の時間帯
  設定が意図した時間からずれる）: `sudo timedatectl set-timezone Asia/Tokyo` → サービス再起動
- ダッシュボードへのアクセスは自宅IP限定のファイアウォールにするのが手軽（クラウドコンソールから
  誰でも見えるURL公開はしない）。自宅のIPが変わったらファイアウォールルールを更新する
- ディスクに自動スナップショットスケジュールが標準で付くことがある。Always Free対象外の
  ストレージ課金になるので、使わないなら外しておく
- 費用の予算アラート（例: $1超えたら通知）をGoogle Cloudの「お支払い」→「予算とアラート」で
  設定しておくと、無料枠を超えた時にすぐ気づける

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
| **`sns`** | 楽天の値下がり・過去最安値をThreadsに自動投稿（リンクあり・PRあり） |
| **`a8`** | A8アフィリリンクをローテーションでThreadsに自動投稿（リンクあり・PRあり） |
| **`digest`** | ジャンル別売れ筋トップ3ダイジェストをThreadsに投稿（リンクあり・PRあり） |
| **`trend`** | ジャンルの週間価格トレンド速報をThreadsに投稿（リンクなし・PR不要） |
| **`calendar`** | セール・お得日のリマインドをThreadsに投稿（リンクなし・PR不要） |
| **`trivia`** | ミニ知識・あるあるネタをThreadsに投稿（リンクなし・PR不要） |
| **`collect`** | 調査専用。広いジャンルの価格スナップショットだけ集める（Claude不使用・実質無料） |
| **`insights`** | Threads投稿の反応をジャンル・商品別に集計して表示 |
| `daily` | 上記フロー1〜5を一括実行（GUIの「おまかせ」と同じ） |

**sns/a8は「値下がり・A8リンクが見つかった時だけ」しか投稿できず出現頻度が低いため、
digest/trend/calendar/triviaは条件に依存しない（値下がりが無くても投稿できる）ネタとして
追加した。投稿数を増やしたい時はこちらの頻度（`config.yaml`の`server.*_runs_per_day`）を
上げるとよい。**

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
サーバー運用にしている場合は、編集後に `sync_a8_links.bat` をダブルクリックしてサーバーに反映する
（詳しい登録フローは上の「調査→A8拡充のループ」参照）。

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
