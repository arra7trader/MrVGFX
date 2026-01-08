@echo off
title MrVgFx Orderbook - VPS Mode (API)
color 0A
cd /d "%~dp0"

echo ===================================================
echo   MrVgFx REAL-TIME ORDERBOOK - VPS MODE
echo   Menggunakan Binance + TwelveData API
echo ===================================================
echo.

echo ===================================================
echo.

:: Step 0: Auto Update
echo [0/5] Mengecek Update MrVgFx...
git pull origin main
echo.

:: Step 1: Kill Previous Process (Fix Port Conflict)
echo [1/5] Membersihkan proses lama...
taskkill /F /IM python.exe /T >nul 2>&1
timeout /t 2 >nul

:: Step 2: Check Python
echo [2/5] Mengecek Python...
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo.
    echo   ERROR: Python tidak terinstall!
    echo.
    echo   Download dan install Python 3.12:
    echo   https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe
    echo.
    echo   PENTING: Centang "Add Python to PATH" saat install!
    echo.
    pause
    exit /b 1
)
echo        Python OK!

:: Step 3: Check/Install dependencies
echo [3/5] Mengecek dependencies...
pip show httpx >nul 2>&1
if errorlevel 1 (
    echo        Installing dependencies...
    pip install websockets httpx --quiet
)
echo        Dependencies OK!

:: Step 4: Start Server
echo [4/5] Menjalankan Server API...
echo.
echo ===================================================
echo   SERVER BERJALAN - Jangan tutup jendela ini!
echo.
echo   Data Source: Binance (Crypto) + TwelveData (Forex)
echo   WebSocket Port: 8776
echo.
echo   Fitur Baru:
echo   - Entry Zone dengan SL/TP
echo   - Bubble Visualization
echo   - Whale Alert
echo ===================================================
echo.

:: Run Python bridge_api.py (tidak perlu MT5!)
python bridge_api.py 2>&1

:: If we get here, server stopped
echo.
echo ===================================================
color 0C
echo   SERVER BERHENTI!
echo.
echo   Jika ada error di atas, screenshot dan kirim ke developer.
echo ===================================================
echo.
echo Tekan tombol untuk keluar...
pause >nul
