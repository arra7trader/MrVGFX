@echo off
title MT5 Orderbook - API Mode (No MT5 Required)
color 0A
cd /d "%~dp0"

echo ===================================================
echo   MT5 REAL-TIME ORDERBOOK - API MODE
echo   by MrVgFx
echo ===================================================
echo.
echo   Data Sources:
echo   - TwelveData: XAUUSD, XAGUSD, Forex
echo   - Binance: BTCUSD, ETHUSD, SOLUSD, XRPUSD
echo.
echo   (Tidak membutuhkan MetaTrader 5)
echo ===================================================
echo.

:: Step 1: Check Python
echo [1/3] Mengecek Python...
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo.
    echo   ERROR: Python tidak terinstall!
    echo   Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
echo        Python OK!

:: Step 2: Check/Install dependencies (NO MetaTrader5!)
echo [2/3] Mengecek dependencies...
pip show websockets >nul 2>&1
if errorlevel 1 (
    echo        Installing dependencies...
    pip install websockets numpy httpx --quiet
)
echo        Dependencies OK!

:: Step 3: Start Server
echo [3/3] Menjalankan Server...
echo.
echo ===================================================
echo   SERVER BERJALAN - Jangan tutup jendela ini!
echo.
echo   Buka browser dan buka file: index.html
echo ===================================================
echo.

python bridge_api.py 2>&1

:: If we get here, server stopped
echo.
echo ===================================================
color 0C
echo   SERVER BERHENTI!
echo   Jika ada error di atas, screenshot dan kirim ke developer.
echo ===================================================
echo.
pause
