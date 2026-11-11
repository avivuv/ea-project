@echo off
title Telegram Scalper - Dashboard
echo ============================================================
echo  Telegram Scalper - Dashboard monitoring
echo  Buka di browser: http://127.0.0.1:8080
echo  Tekan Ctrl+C untuk berhenti.
echo ============================================================
cd /d c:\laragon\www\ea-project\backend
start "" http://127.0.0.1:8080
C:\laragon\bin\python\python-3.10\python.exe -m tg_signal.dashboard
echo.
echo Dashboard berhenti.
pause
