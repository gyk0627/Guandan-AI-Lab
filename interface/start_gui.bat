@echo off
chcp 65001 >nul
cd /d "%~dp0.."

echo ============================================================
echo  掼蛋人机对战
echo ============================================================
echo  关闭本窗口即结束。
echo.

".venv\Scripts\python.exe" -m interface.web_server %*

pause
