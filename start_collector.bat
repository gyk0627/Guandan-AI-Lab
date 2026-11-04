@echo off
REM Keep this window open while friends play: it receives their game logs.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo ============================================================
echo  Guandan log collector
echo  Listening on port 8790, saving to the "collected" folder.
echo  Leave this window open (you may minimize it).
echo  Close it and no more logs will be received.
echo ============================================================
echo.
".venv\Scripts\python.exe" -X utf8 -m tools.collect_server --dir collected --port 8790 --token guandan-local
echo.
echo Collector stopped. Press any key to close.
pause >nul
