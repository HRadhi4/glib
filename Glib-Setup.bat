@echo off
setlocal
title Glib Setup
set "DEST=%LOCALAPPDATA%\Glib"
set "TMPZIP=%TEMP%\glib-setup.zip"
set "TMPDIR=%TEMP%\glib-setup"
echo.
echo  ==========================================
echo    Glib Setup
echo  ==========================================
echo.
echo  Glib will be installed in:
echo    %DEST%
echo.
echo  It needs about 4 GB of free space and an internet connection.
echo.
pause

echo.
echo  Downloading Glib...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing 'https://github.com/HRadhi4/glib/archive/refs/heads/main.zip' -OutFile $env:TMPZIP"
if errorlevel 1 goto failed
if not exist "%TMPZIP%" goto failed

echo  Unpacking...
if exist "%TMPDIR%" rmdir /s /q "%TMPDIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath $env:TMPZIP -DestinationPath $env:TMPDIR -Force"
if errorlevel 1 goto failed
if not exist "%TMPDIR%\glib-main\Install Glib.bat" goto failed

if not exist "%DEST%" mkdir "%DEST%"
robocopy "%TMPDIR%\glib-main" "%DEST%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto failed
rmdir /s /q "%TMPDIR%"
del "%TMPZIP%" >nul 2>&1

cd /d "%DEST%"
call "Install Glib.bat"
exit /b %errorlevel%

:failed
echo.
echo  Glib could not be downloaded or unpacked. Check the internet connection and
echo  run this file again. Nothing was changed on your computer.
echo.
pause
exit /b 1
