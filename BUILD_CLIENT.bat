@echo off
title MrVgFx - BUILD RELEASE
color 0B
cd /d "%~dp0"

echo ===================================================
echo   BUILDING CLIENT RELEASE PACKAGE
echo ===================================================
echo.

set RELEASE_DIR=RELEASE_CLIENT_v2

:: 1. Clean previous build
if exist "%RELEASE_DIR%" (
    echo [1/4] Cleaning old release...
    rmdir /s /q "%RELEASE_DIR%"
)
mkdir "%RELEASE_DIR%"

:: 2. Copy Key Files
echo [2/4] Copying Core Files...
copy "index.html" "%RELEASE_DIR%\" >nul
copy "bridge_api.py" "%RELEASE_DIR%\" >nul
copy "START_CLIENT.bat" "%RELEASE_DIR%\" >nul
copy "PANDUAN_CLIENT.txt" "%RELEASE_DIR%\" >nul

:: 3. Copy Directories
echo [3/4] Copying Modules...
xcopy "api" "%RELEASE_DIR%\api\" /E /I /Y >nul
xcopy "bookmap" "%RELEASE_DIR%\bookmap\" /E /I /Y >nul

:: 4. Finish
echo [4/4] Build Complete!
echo.
echo ===================================================
echo   RELEASE READY IN FOLDER: %RELEASE_DIR%
echo ===================================================
echo.
echo   Silakan "Right Click -> Send to -> Compressed (zipped) folder"
echo   pada folder "%RELEASE_DIR%" untuk dikirim ke client.
echo.
pause
