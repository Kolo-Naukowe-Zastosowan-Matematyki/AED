@echo off
rem Mapa AED: zatrzymanie serwera uruchomionego z tego folderu.
setlocal
cd /d "%~dp0"
if not exist "data\server.pid" (
  if /i not "%~1"=="cicho" echo Serwer AED nie jest uruchomiony z tego folderu.
  exit /b 0
)
set "PID="
for /f "usebackq tokens=1,2" %%a in ("data\server.pid") do (
  set "PID=%%a"
  set "PORT=%%b"
)
if defined PID (
  tasklist /FI "PID eq %PID%" /NH 2>nul | find /i "python" >nul && (
    taskkill /PID %PID% /F >nul 2>&1
    echo Zatrzymano poprzedni serwer AED, port %PORT%.
    timeout /t 1 /nobreak >nul
  )
)
del "data\server.pid" >nul 2>&1
exit /b 0
