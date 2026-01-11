@echo off
title MrVgFx Dashboard
color 0A

========================================
  MRVGFX DASHBOARD PREMIERE
========================================

[1/2] Membuka Dashboard...
start "" "index.html"

[2/2] Menjalankan Konektor...
start "" "MrVgFx_Connector.exe"

APLIKASI BERJALAN! Jangan tutup jendela ini.

Minimize saja window ini.

Tekan spasi jika ingin menutup aplikasi...
pause >nul
taskkill /F /IM MrVgFx_Connector.exe >nul 2>&1
