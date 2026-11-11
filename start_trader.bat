@echo off
title Telegram Scalper - Trader (DEMO)
echo ============================================================
echo  Telegram Scalper - Trader (akun DEMO)
echo  Pastikan MT5 terbuka dan tombol "Algo Trading" menyala.
echo  Tekan Ctrl+C untuk berhenti.
echo ============================================================
cd /d c:\laragon\www\ea-project\backend
C:\laragon\bin\python\python-3.10\python.exe -m tg_signal.run_live --mode DEMO
echo.
echo Trader berhenti.
pause
