@echo off
title OmniDrop - Social Video Downloader
cd /d "%~dp0"

echo ====================================================
echo   OmniDrop - Social Video Downloader Launching...
echo ====================================================

:: Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo [1/3] Creating Python virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Python is not installed or not in PATH!
        pause
        exit /b 1
    )
)

echo [2/3] Activating virtual environment & installing dependencies...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt

echo [3/3] Opening browser and starting server...
start http://127.0.0.1:5000

echo.
echo Application running at: http://127.0.0.1:5000
echo Press Ctrl+C in this terminal window to stop the server.
echo.

python app.py
pause
