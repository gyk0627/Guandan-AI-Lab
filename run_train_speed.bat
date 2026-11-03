@echo off
rem Training speed meter: measure one epoch of BC training and value-network training.
rem Double-click to run, or pass args:  run_train_speed.bat --task value
setlocal
cd /d "C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python venv not found. The path may be wrong.
  pause
  exit /b 1
)

echo ============================================================
echo  GuanDan AI Lab - training speed meter
echo ============================================================
echo.

".venv\Scripts\python.exe" -X utf8 -u -m tools.train_speed %*

echo.
echo Done. Press any key to close.
pause
