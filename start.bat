@echo off
rem Mapa AED: uruchomienie (albo restart) portalu z modulem AED. Dwuklik w Eksploratorze.
setlocal
cd /d "%~dp0"
title Mapa AED - serwer
call "%~dp0stop.bat" cicho

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Nie znaleziono Pythona. Zainstaluj Python 3.9+ z python.org i zaznacz "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist "frontend\dist\index.html" (
  echo Brak zbudowanego frontendu w frontend\dist. Rozpakuj pelna paczke aed-prototyp.zip.
  pause
  exit /b 1
)

echo Uruchamiam portal z modulem AED. Przegladarka otworzy sie sama.
echo Aby zatrzymac: zamknij to okno albo nacisnij Ctrl+C. Restart: uruchom start.bat ponownie.
echo.
%PY% server.py --open %*
echo.
echo Serwer zatrzymany.
pause
