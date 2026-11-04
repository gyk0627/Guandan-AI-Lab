@echo off
rem GuanDan AI Lab - train with a live progress page (ASCII only on purpose:
rem Chinese text in .bat breaks under the ANSI code page).
setlocal
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Run from the project root after creating the venv.
  pause
  exit /b 1
)

echo ==============================================================
echo  Training with live progress page
echo  The browser opens automatically. Close this window to stop.
echo ==============================================================
echo.

".venv\Scripts\python.exe" -X utf8 -m tools.train_with_monitor %*

echo.
pause
