@echo off
rem Speed test: generate N games, then export, and print games/sec and samples/sec.
rem Double-click to run 500 games, or pass a number:  run_speed_test.bat 20
setlocal
set GAMES=%1
if "%GAMES%"=="" set GAMES=500

cd /d "C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python venv not found. The path may be wrong.
  pause
  exit /b 1
)

echo ============================================================
echo  GuanDan AI Lab - speed test - %GAMES% games
echo ============================================================
echo.

".venv\Scripts\python.exe" -X utf8 -u -m tools.speed_test --games %GAMES%

echo.
echo Done. Press any key to close.
pause
