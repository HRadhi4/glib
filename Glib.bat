@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Glib is not installed yet. Double-click "Install Glib" first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m glib
