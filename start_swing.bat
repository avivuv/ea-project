@echo off
title Swing Trend-Following - Trader (DEMO)
echo ============================================================
echo  Swing trend-following (Donchian) - XAUUSD / BTCUSD / USDJPY
echo  Akun DEMO saja. Pastikan MT5 terbuka dan "Algo Trading" menyala.
echo  Berjalan bersamaan dengan scalper (magic number berbeda).
echo  Tekan Ctrl+C untuk berhenti.
echo ============================================================
cd /d c:\laragon\www\ea-project\backend
C:\laragon\bin\python\python-3.10\python.exe -m intraday.swing_live
echo.
echo Swing trader berhenti.
pause
