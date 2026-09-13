@echo off
rem サーバー側で自動追記されたA8依頼の最新版を、別ファイルとして取得します。
rem ntfyの通知が来たら、これをダブルクリック → 出力されたファイルを見て、
rem 新しく追加された「追加調査依頼」セクションだけを、コワーカーに渡している
rem 本体の docs\A8アフィリリンク取得依頼.md に手動でコピーしてください。
rem （本体を直接上書きしないのは、コワーカーが書き込み済みのリンクを消さないため）
set PATH=%PATH%;C:\Users\kirui\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin
echo サーバー側の最新版を取得します...
gcloud compute scp instance-20260913-030032:"/home/kirui/rakuten_room/docs/A8アフィリリンク取得依頼.md" "%~dp0docs\A8アフィリリンク取得依頼_サーバー最新版.md" --zone us-central1-a
echo.
echo 完了しました。docs\A8アフィリリンク取得依頼_サーバー最新版.md を確認してください。
echo 新しいセクションだけを本体ファイルにコピーしてから、このファイルは削除して構いません。
pause
