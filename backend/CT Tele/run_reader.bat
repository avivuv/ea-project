   @echo off
   title TG Signal Reader
   cd /d %~dp0
   :loop
   python tg_signal_reader.py
   echo.
   echo Pembaca sinyal berhenti. Restart otomatis dalam 10 detik...
   timeout /t 10 /nobreak >nul
   goto loop