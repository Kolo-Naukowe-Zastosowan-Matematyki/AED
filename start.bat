@echo off
cd /d "%~dp0"
wsl -d Ubuntu -u root -- sh start.sh
if errorlevel 1 (
  pause
  exit /b 1
)
call demo.bat
cd mcod
wsl -d Ubuntu -u root -- docker compose --env-file ../../.raed-lokalne/mcod.env -p aed2 -f docker-compose.local.yml -f compose.aed.yml logs -f --tail=0 rejestr

