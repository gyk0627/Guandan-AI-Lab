@echo off
rem Build a double-clickable Windows package (folder + zip) for the GUI.
rem Output: dist\GuandanAI\GuandanAI.exe and dist\GuandanAI-win64.zip
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python venv not found: .venv\Scripts\python.exe
    echo Create it first, then run this again.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -X utf8 -m tools.package_exe %*
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. See the messages above.
    pause
    exit /b 1
)

echo.
pause
