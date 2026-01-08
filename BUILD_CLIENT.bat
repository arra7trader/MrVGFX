@echo off
title MrVgFx - Building Client Version
color 0B

echo ===================================================
echo   MEMBUAT VERSI CLIENT (EXE)
echo   Agar bisa jalan di PC tanpa Python/Git
echo ===================================================
echo.

:: 1. Install PyInstaller
echo [1/4] Installing PyInstaller...
pip install pyinstaller --quiet

:: 2. Clean previous build
echo [2/4] Membersihkan folder lama...
rmdir /s /q build dist CLIENT_RELEASE 2>nul

:: 3. Compile to EXE
echo [3/4] Mengkompilasi program (ini agak lama)...
:: --onefile: Single .exe file
:: --name: Name of the exe
:: --icon: (Optional) Icon file if you have one, skipped for now
pyinstaller --onefile --name "MrVgFx_Connector" --clean bridge_api.py

:: 4. Organize Release Folder
echo [4/4] Menyiapkan folder release...
mkdir CLIENT_RELEASE
copy "dist\MrVgFx_Connector.exe" "CLIENT_RELEASE\" >nul
copy "index.html" "CLIENT_RELEASE\" >nul

:: Create a simple launcher for the client
(
echo @echo off
echo title MrVgFx Dashboard
echo color 0A
echo.
echo ========================================
echo   MRVGFX DASHBOARD PREMIERE
echo ========================================
echo.
echo [1/2] Membuka Dashboard...
echo start "" "index.html"
echo.
echo [2/2] Menjalankan Konektor...
echo start "" "MrVgFx_Connector.exe"
echo.
echo APLIKASI BERJALAN! Jangan tutup jendela ini.
echo.
echo Minimize saja window ini.
echo.
echo Tekan spasi jika ingin menutup aplikasi...
echo pause ^>nul
echo taskkill /F /IM MrVgFx_Connector.exe ^>nul 2^>^&1
) > "CLIENT_RELEASE\START_MRVGFX.bat"

echo.
echo ===================================================
echo   SELESAI!
echo.
echo   Folder Client ada di: CLIENT_RELEASE
echo   
echo   Silakan ZIP folder 'CLIENT_RELEASE' itu
echo   dan kirim ke klien Anda.
echo ===================================================
echo.
pause
