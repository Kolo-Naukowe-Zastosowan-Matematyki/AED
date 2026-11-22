@echo off
setlocal
set "AED_BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%AED_BROWSER%" set "AED_BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%AED_BROWSER%" (
  echo Zobacz konfiguracje domen w README.md.
  pause
  exit /b 1
)
start "" "%AED_BROWSER%" --user-data-dir="%LOCALAPPDATA%\MisjaAED\profil-demo" --no-first-run --host-resolver-rules="MAP mcod.local 127.0.0.1, MAP *.mcod.local 127.0.0.1" --ignore-certificate-errors-spki-list="vyNjCTt3CSJOf4d5MGMi3iPqrIOAF3NilhZtqegJ/kA=" https://mcod.local/pl

