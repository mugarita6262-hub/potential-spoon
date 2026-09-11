# Kindle出版パイプライン（企画〜原稿ドラフト）

Kindle電子書籍(KDP)の企画・原稿ドラフトを Claude API で生成する。
**最終チェックと公開(KDP管理画面へのアップロード)は人間が行う** — 完全自動出版はしない。
理由: KDPに個人のセルフ出版APIは無く手動アップロードが前提であること、
そして生成AI利用時のAmazon申告義務・1日3冊の出版上限があるため、
最終確認と申告判断を人が持つのが安全かつ規約に沿う。

## セットアップ

```
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`.env` に `ANTHROPIC_API_KEY` を設定（無ければ隣の `rakuten_room/.env` のキーを自動で使う）。

## 使い方

```
.venv\Scripts\python.exe -m src.main ideas [テーマのヒント]
```

企画候補（書名・想定読者・章立て・キーワード等）を生成し、
`data/ideas_latest.json` に保存。気に入ったものを選んで原稿ドラフトへ進む
（`draft` コマンドは次のステップで追加予定）。

## 方針

- 規制業種（医療・法律・投資の断定的助言）は避ける
- Amazonの生成AI利用申告を必ず行う
- 出版は1日3冊の上限を超えない
- 公開前に人が原稿とメタデータを確認する
