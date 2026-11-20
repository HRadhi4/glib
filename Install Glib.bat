@echo off
setlocal
cd /d "%~dp0"
title Installing Glib
echo.
echo  ==========================================
echo    Installing Glib  (this is done only once)
echo  ==========================================
echo.

set "PY="
py -3.13 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3.13"
if defined PY goto havepy
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe""
if defined PY goto havepy
if exist "%ProgramFiles%\Python313\python.exe" set "PY="%ProgramFiles%\Python313\python.exe""
if defined PY goto havepy

echo  Step 1 of 4: Python 3.13 is needed. Installing it now...
winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe""
if defined PY goto havepy
echo.
echo  Python could not be installed automatically.
echo  Please install "Python 3.13 (64-bit)" from https://www.python.org/downloads/windows/
echo  then double-click "Install Glib" again.
echo.
pause
exit /b 1

:havepy
echo  Step 1 of 4: Python found.
echo  Step 2 of 4: Preparing Glib's own folder...
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
if not exist ".venv\Scripts\python.exe" goto failed
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet

echo  Step 3 of 4: Installing the parts Glib needs (about 1 GB, a few minutes)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt --only-binary :all: --quiet --disable-pip-version-check
if errorlevel 1 goto failed

echo  Step 4 of 4: Downloading the voice engines (about 2.3 GB)...
".venv\Scripts\python.exe" -m glib.models
if errorlevel 1 echo  The download did not finish. You can finish it later from inside Glib.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Glib.lnk'); $s.TargetPath=(Join-Path (Get-Location) '.venv\Scripts\pythonw.exe'); $s.Arguments='-m glib'; $s.WorkingDirectory=(Get-Location).Path; $s.IconLocation=(Join-Path (Get-Location) 'assets\glib.ico'); $s.Save()" >nul 2>&1

echo.
echo  Glib is installed. A "Glib" icon is now on your desktop.
echo  Starting Glib...
start "" ".venv\Scripts\pythonw.exe" -m glib
echo.
pause
exit /b 0

:failed
echo.
echo  Something went wrong during the installation. Nothing on your computer was changed
echo  outside this folder. Take a photo of this window and send it for help.
echo.
pause
exit /b 1
