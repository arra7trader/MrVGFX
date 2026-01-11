@echo off
title Debug MrVgFx VPS Mode
color 0e
cd /d "%~dp0"

echo ===================================================
echo   DEBUG MODE - START_VPS
echo ===================================================
echo.

echo [1/3] Checking Ports...
netstat -ano | findstr :8776
echo.

echo [2/3] Opening Dashboard...
start "" "%~dp0index.html"
timeout /t 2 >nul

echo [3/3] Starting Bridge API (Python)...
python bridge_api.py
if %errorlevel% neq 0 (
    color 0c
    echo.
    echo [ERROR] Python Bridge Crashed!
    echo Error Code: %errorlevel%
    echo.
    echo Press any key to exit...
    pause
)
