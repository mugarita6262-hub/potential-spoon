@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
echo ==== %date% %time% ==== >> "logs\prune.log"
".venv\Scripts\python.exe" -m src.main prune --commit --max 100 >> "logs\prune.log" 2>&1
