@echo off
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe

echo [1/2] prepare today items...
%PY% -m src.main prepare

echo.
echo [2/2] post...
%PY% -m src.main post

echo.
echo done.
pause
