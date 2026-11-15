@echo off
rem ======================================================================
rem  Satu file untuk semua program trading (akun DEMO):
rem    trading.bat           menu
rem    trading.bat start     nyalakan semua (yang sudah jalan dilewati)
rem    trading.bat stop      hentikan semua (posisi/pending di MT5 tetap)
rem    trading.bat status    cek program mana yang jalan
rem  Tiap program jalan di jendela sendiri (diminimize) dan restart
rem  otomatis 10 detik bila crash.
rem ======================================================================
setlocal
set "PY=C:\laragon\bin\python\python-3.10\python.exe"
set "BACKEND=c:\laragon\www\ea-project\backend"
if /i "%~1"=="run" goto run
if /i "%~1"=="start" goto startall
if /i "%~1"=="stop" goto stopall
if /i "%~1"=="status" goto status

:menu
cls
echo ============================================================
echo   TRADING XAUUSD - akun DEMO
echo ============================================================
call :status_list
echo ------------------------------------------------------------
echo   1. Start semua  (EA sinyal, swing, SMC Top-Down, dashboard)
echo   2. Stop semua   (posisi dan pending di MT5 TIDAK ditutup)
echo   3. Buka dashboard di browser
echo   4. Refresh status
echo   5. Keluar
echo ------------------------------------------------------------
choice /c 12345 /n /m "Pilih [1-5]: "
if errorlevel 5 exit /b
if errorlevel 4 goto menu
if errorlevel 3 start "" http://127.0.0.1:8080 & goto menu
if errorlevel 2 goto stop_confirm
call :do_start
start "" http://127.0.0.1:8080
timeout /t 5 >nul
goto menu

:stop_confirm
choice /m "Yakin hentikan semua program"
if errorlevel 2 goto menu
call :do_stop
timeout /t 4 >nul
goto menu

:startall
call :do_start
exit /b

:stopall
call :do_stop
exit /b

:status
call :status_list
exit /b

:do_start
echo Pastikan MT5 terbuka dan tombol "Algo Trading" menyala.
call :launch tg_signal.run_live "EA sinyal" "tg_signal.run_live --mode DEMO"
call :launch intraday.swing_live "Swing" "intraday.swing_live"
call :launch tg_signal.pro_live "SMC Top-Down" "tg_signal.pro_live --mode DEMO"
call :launch tg_signal.dashboard "Dashboard" "tg_signal.dashboard"
exit /b

:launch
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*%~1*' }) { exit 1 } else { exit 0 }"
if errorlevel 1 goto launch_skip
echo   - menyalakan %~2
start "TRADING %~2" /min cmd /c ""%~f0" run %~3"
timeout /t 3 /nobreak >nul
exit /b
:launch_skip
echo   - %~2 sudah jalan, dilewati
exit /b

:do_stop
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | Where-Object { $_.CommandLine -match 'ea-project\\start_\w+\.bat|trading\.bat. run' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'tg_signal\.(run_live|pro_live|dashboard)|intraday\.swing_live' } | ForEach-Object { Write-Host ('  stop ' + ($_.CommandLine -split ' -m ')[-1] + '  (PID ' + $_.ProcessId + ')'); Stop-Process -Id $_.ProcessId -Force }"
echo   Semua program dihentikan.
exit /b

:status_list
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\"; foreach ($m in @('tg_signal.run_live|EA sinyal Telegram','intraday.swing_live|Swing Donchian','tg_signal.pro_live|SMC Top-Down','tg_signal.dashboard|Dashboard')) { $k,$n = $m.Split('|'); $x = $p | Where-Object { $_.CommandLine -like ('*' + $k + '*') } | Select-Object -First 1; if ($x) { Write-Host ('  [JALAN] ' + $n + '  sejak ' + $x.CreationDate.ToString('dd/MM HH:mm')) -ForegroundColor Green } else { Write-Host ('  [MATI ] ' + $n) -ForegroundColor Red } }"
exit /b

:run
title TRADING %2
cd /d "%BACKEND%"
:loop
"%PY%" -m %2 %3 %4
echo.
echo %2 berhenti. Restart otomatis dalam 10 detik - tutup jendela ini untuk berhenti.
timeout /t 10 /nobreak >nul
goto loop
