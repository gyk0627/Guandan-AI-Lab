@echo off
chcp 65001 >nul
cd /d "%~dp0.."

echo ============================================================
echo   Guandan: human vs AI  (web GUI)
echo ============================================================
echo   Close this window to stop the server.
echo.

".venv\Scripts\python.exe" -X utf8 -m interface.web_server %*

pause
