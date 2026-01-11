@echo off
title MrVgFx PRO TRADER SUITE
color 0B
cd /d "%~dp0"

echo ===================================================
echo   MrVgFx PRO TRADER SUITE (CLIENT VERSION)
echo   Real-Time Market Data & Analysis
echo ===================================================
echo.

:: Step 1: Check Python
echo [1/3] Mengecek System...
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo.
    echo   [ERROR] Python tidak ditemukan!
    echo.
    echo   Silakan install Python 3.12 dari website resmi python.org
    echo   PENTING: Centang "Add Python to PATH" saat install.
    echo.
    pause
    exit /b 1
)

:: Step 2: Dependencies
echo [2/3] Memastikan Driver Terinstall...
pip install websockets httpx --quiet

:: Step 3: Launch
echo [3/3] Menjalankan Aplikasi...
echo.
echo   [INFO] Browser akan terbuka otomatis.
echo   [INFO] JANGAN TUTUP jendela hitam ini selama trading.
echo.

:: Open Main Dashboard
start "" "%~dp0index.html"

:: Run Bridge Core
python bridge_api.py

:: If stopped
pause
