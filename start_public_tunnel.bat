@echo off
title Clipwave Global Public Server
echo ===================================================
echo   Starting Clipwave Video Downloader (Global Tunnel)
echo ===================================================

cd /d "%~dp0"

echo [1/2] Starting Flask Backend Server...
start "" "venv\Scripts\python.exe" app.py

timeout /t 2 >nul

echo [2/2] Connecting to Cloudflare Global Edge Network...
echo.
echo ===================================================
echo Your Public Website URL will appear below:
echo (Share this URL with anyone or use on your phone!)
echo ===================================================
.\cloudflared.exe tunnel --url http://127.0.0.1:5000
pause
