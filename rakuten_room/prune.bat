@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m src.main prune --commit --max 100
pause
