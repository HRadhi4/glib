@echo off
setlocal
cd /d "%~dp0"
title Glib - extra engines
if not exist ".venv\Scripts\python.exe" (
  echo Install Glib first.
  pause
  exit /b 1
)
echo.
echo  This adds two optional engines (about 2 GB more):
echo    - Chatterbox: a second voice converter you can choose in Settings
echo    - Whisper: a second listener
echo  Close Glib before you continue.
echo.
pause
".venv\Scripts\python.exe" -m pip install -r requirements-extra.txt --only-binary :all: --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo  The extra engines could not be installed. Glib itself still works as before.
) else (
  echo.
  echo  Done. Open Glib, then Settings, to choose the Chatterbox converter.
)
pause
