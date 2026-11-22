@echo off
cd /d "%~dp0mcod"
wsl -d Ubuntu -u root -- docker compose --env-file ../../.raed-lokalne/mcod.env -p aed2 -f docker-compose.local.yml -f compose.aed.yml stop

