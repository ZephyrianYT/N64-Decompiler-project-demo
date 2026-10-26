@echo off
rem Double-click to start the n64lab web UI and open it in your browser.
rem Projects are kept in the n64lab_workspace folder next to this file.
setlocal
cd /d "%~dp0"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
    echo Python 3.8 or newer is required: https://www.python.org/downloads/
    pause
    exit /b 1
)
%PY% -m n64lab ui --open
pause
