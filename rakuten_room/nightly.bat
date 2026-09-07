@echo off
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe

echo [1/3] prune old posts...
%PY% -m src.main prune --commit

echo.
echo [2/3] prepare today items...
%PY% -m src.main prepare

echo.
echo [3/3] post...
%PY% -m src.main post

echo.
echo done.
pause
