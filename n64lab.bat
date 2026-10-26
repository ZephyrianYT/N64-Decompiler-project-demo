@echo off
rem Drag an N64 ROM (.z64, .n64 or .v64) onto this file to recompile it into a
rem Windows program and run it.  Needs Python 3.8+ and a C compiler (MinGW-w64
rem gcc, LLVM clang, or Visual Studio's cl in a Developer Command Prompt).
setlocal
cd /d "%~dp0"
if "%~1"=="" (
    echo Drag a .z64 / .n64 / .v64 ROM onto n64lab.bat to recompile and run it.
    echo Or use the command line: python -m n64lab --help
    pause
    exit /b 1
)
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
    echo Python 3.8 or newer is required: https://www.python.org/downloads/
    pause
    exit /b 1
)
set "SYMBOLS="
if exist "%~dpn1.sym" set "SYMBOLS=--symbols "%~dpn1.sym""
%PY% -m n64lab recomp "%~1" -o "%~dpn1_recomp" %SYMBOLS% --run
echo.
echo The generated C project is in "%~dpn1_recomp".
pause
