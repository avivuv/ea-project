@echo off
echo Stopping EA Backend...
taskkill /f /im python.exe 2>nul
timeout /t 2 /nobreak >nul
echo Starting EA Backend...
cd /d c:\laragon\www\ea-project\backend
C:\laragon\bin\python\python-3.10\python.exe main.py
pause
