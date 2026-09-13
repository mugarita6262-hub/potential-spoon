@echo off
rem サーバー側で自動的に起きたこと（ジャンル自動昇格・A8追加依頼）をローカルに取り込みます。
rem ntfyの通知が来たら、これをダブルクリックしてください。
set PATH=%PATH%;C:\Users\kirui\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin
set INSTANCE=instance-20260913-030032
set ZONE=us-central1-a

echo [1/2] 自動昇格したジャンルをconfig.yamlに取り込みます...
gcloud compute scp %INSTANCE%:/home/kirui/rakuten_room/config.yaml "%TEMP%\rr_server_config.yaml" --zone %ZONE%
".venv\Scripts\python.exe" sync_promoted_genres.py "%TEMP%\rr_server_config.yaml"

echo.
echo [2/2] A8追加依頼の最新版を取得します...
gcloud compute scp %INSTANCE%:"/home/kirui/rakuten_room/docs/A8アフィリリンク取得依頼.md" "%~dp0docs\A8アフィリリンク取得依頼_サーバー最新版.md" --zone %ZONE%
echo   → docs\A8アフィリリンク取得依頼_サーバー最新版.md を確認し、新しいセクションだけ
echo     本体の docs\A8アフィリリンク取得依頼.md に手動でコピーしてください
echo     （本体はコワーカーが書き込み済みなので、自動上書きしない設計です）

echo.
echo 完了しました。
pause
