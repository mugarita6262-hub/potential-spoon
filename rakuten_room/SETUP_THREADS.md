# Threads自動投稿のセットアップ（初回のみ）

`sns` コマンド（値下がり・過去最安値の商品をThreadsに自動投稿）を使うには、
Meta公式の Threads API のアクセストークンが必要です。以下は初回だけの手作業です。
（一度取れば、以降のトークン延長は `sns` 実行のたびに自動で行われます）

## 1. Threadsのプロアカウントを用意する
- ThreadsはInstagramのアカウントと連携しています。投稿に使うInstagramアカウントを
  「プロアカウント（ビジネス or クリエイター）」に切り替えてください
  （Instagramアプリ → プロフィール編集 → プロアカウントに切り替え）。
- そのアカウントでThreadsアプリにログインしておく。

## 2. Meta Developerアプリを作る
1. https://developers.facebook.com/ にログイン（普段使っているFacebookアカウントでOK）。
2. 「マイアプリ」→「アプリを作成」。用途は「その他」→「ビジネス」を選択。
3. 作成したアプリのダッシュボードで「製品を追加」→ **Threads API** を追加。
4. 「Threads API」の設定画面で、自分のThreadsアカウント（1で用意したもの）を
   「Threadsテスターとして追加」する（個人利用なのでアプリ審査は不要）。
5. Threadsアプリ側（またはThreads.netからのメール/通知）でテスター招待を承認する。

## 3. アクセストークンを取得する
1. 「Threads API」設定画面の「Generate Access Token」（または「アクセストークンの生成」）から、
   自分のアカウント向けの短期アクセストークンを発行する。
   - 必要な権限（scope）: `threads_basic`, `threads_content_publish`
2. 短期トークンを長期トークン（60日）に交換する。ブラウザで下記URLを開く
   （`{短期トークン}` と `{アプリのシークレット}` を置き換える。シークレットはアプリ設定の「基本設定」にあります）:
   ```
   https://graph.threads.net/access_token
     ?grant_type=th_exchange_token
     &client_secret={アプリのシークレット}
     &access_token={短期トークン}
   ```
   返ってきたJSONの `access_token` が長期トークン。これを `.env` の `THREADS_ACCESS_TOKEN` に設定。

## 4. THREADS_USER_ID を取得する
ブラウザで下記URLを開く（`{長期トークン}` を置き換える）:
```
https://graph.threads.net/v1.0/me?fields=id,username&access_token={長期トークン}
```
返ってきた `id` の値を `.env` の `THREADS_USER_ID` に設定。

## 5. .env に記入
```
THREADS_ACCESS_TOKEN=（3で取得した長期トークン）
THREADS_USER_ID=（4で取得したid）
```

## 6. 動作確認
```
python -m src.main sns
```
値下がり品が見つかれば投稿されます。初日〜数日は価格の比較対象がまだ無いため
「対象なし」と出るのが正常です（毎日実行して価格履歴が積み上がるほど検知精度が上がります）。

## トークンの期限について
長期トークンは発行から60日で失効しますが、`sns` コマンドを実行するたびに
自動で延長（さらに60日）されるので、**普段は何もしなくてOK**です。
ただし60日以上「おまかせ」や `sns` を実行しない期間があると失効するので、
その場合は本手順の3〜5をもう一度行ってください。
