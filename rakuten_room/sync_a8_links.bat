@echo off
rem data/a8_links.yaml を編集したあと、これをダブルクリックするとサーバーに反映されます。
set PATH=%PATH%;C:\Users\kirui\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin
echo data/a8_links.yaml をサーバーに転送します...
gcloud compute scp "%~dp0data\a8_links.yaml" instance-20260913-030032:/home/kirui/rakuten_room/data/a8_links.yaml --zone us-central1-a
echo.
echo 完了しました。
pause
