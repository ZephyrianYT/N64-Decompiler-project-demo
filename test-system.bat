@echo off
REM BanjoRecomp - System Verification Test
REM Run this to check if your system is ready

setlocal enabledelayedexpansion

echo.
echo ╔═══════════════════════════════════════════════════════════════╗
echo ║                                                               ║
echo ║         BANJO-KAZOOIE RECOMPILER - SYSTEM CHECK              ║
echo ║                                                               ║
echo ╚═══════════════════════════════════════════════════════════════╝
echo.

set ERRORS=0
set WARNINGS=0

REM Test 1: Check Windows version
echo [1/7] Checking Windows version...
ver | find "Windows" >nul
if %ERRORLEVEL% == 0 (
    echo       ✓ Windows detected
) else (
    echo       ✗ Windows not detected ^(are you on Windows?^)
    set /a ERRORS+=1
)

REM Test 2: Check Python
echo [2/7] Checking Python installation...
where python >nul 2>&1
if %ERRORLEVEL% == 0 (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
    echo       ✓ !PYTHON_VERSION! found
    
    REM Check if Python 3.8+
    for /f "tokens=2 delims=. " %%a in ("!PYTHON_VERSION!") do set PY_MAJOR=%%a
    for /f "tokens=3 delims=. " %%a in ("!PYTHON_VERSION!") do set PY_MINOR=%%a
    
    if !PY_MAJOR! GEQ 3 (
        if !PY_MINOR! GEQ 8 (
            echo       ✓ Version is 3.8 or higher
        ) else (
            echo       ⚠ Warning: Python 3.8+ recommended
            set /a WARNINGS+=1
        )
    )
) else (
    echo       ✗ Python not found
    echo       Install from: https://www.python.org/downloads/
    echo       Make sure to check "Add Python to PATH"
    set /a ERRORS+=1
)

REM Test 3: Check pip
echo [3/7] Checking pip...
where pip >nul 2>&1
if %ERRORLEVEL% == 0 (
    for /f "tokens=*" %%i in ('pip --version 2^>^&1') do set PIP_VERSION=%%i
    echo       ✓ pip found
) else (
    echo       ⚠ pip not found ^(usually comes with Python^)
    set /a WARNINGS+=1
)

REM Test 4: Check Capstone
echo [4/7] Checking Capstone library...
python -c "import capstone" 2>nul
if %ERRORLEVEL% == 0 (
    echo       ✓ Capstone is installed
) else (
    echo       ✗ Capstone not installed
    echo       Run: pip install capstone
    set /a ERRORS+=1
)

REM Test 5: Check for C compiler
echo [5/7] Checking C compiler...
set COMPILER_FOUND=0

where gcc >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo       ✓ GCC found
    set COMPILER_FOUND=1
    goto compiler_done
)

where cl >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo       ✓ MSVC found
    set COMPILER_FOUND=1
    goto compiler_done
)

where clang >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo       ✓ Clang found
    set COMPILER_FOUND=1
    goto compiler_done
)

:compiler_done
if %COMPILER_FOUND% == 0 (
    echo       ✗ No C compiler found
    echo       Install GCC, MSVC, or Clang
    set /a ERRORS+=1
)

REM Test 6: Check if BanjoRecomp.exe exists
echo [6/7] Checking BanjoRecomp.exe...
if exist "BanjoRecomp.exe" (
    echo       ✓ BanjoRecomp.exe found
) else (
    echo       ⚠ BanjoRecomp.exe not found
    echo       Run: compile.bat to build it
    set /a WARNINGS+=1
)

REM Test 7: Check if script exists
echo [7/7] Checking BanjoRecomp.ps1...
if exist "BanjoRecomp.ps1" (
    echo       ✓ BanjoRecomp.ps1 found
) else (
    echo       ✗ BanjoRecomp.ps1 not found
    echo       This file must be in the same folder
    set /a ERRORS+=1
)

echo.
echo ═══════════════════════════════════════════════════════════════
echo.

REM Summary
if %ERRORS% == 0 (
    if %WARNINGS% == 0 (
        echo   ╔═══════════════════════════════════════════════════════════╗
        echo   ║                                                           ║
        echo   ║              ✓ ALL CHECKS PASSED!                        ║
        echo   ║                                                           ║
        echo   ║   Your system is ready to use BanjoRecomp                ║
        echo   ║                                                           ║
        echo   ╚═══════════════════════════════════════════════════════════╝
        echo.
        echo   Next steps:
        echo     1. Drag your Banjo-Kazooie ROM onto BanjoRecomp.exe
        echo     2. Wait for the process to complete
        echo     3. Check your Desktop for the output
        echo.
    ) else (
        echo   ╔═══════════════════════════════════════════════════════════╗
        echo   ║                                                           ║
        echo   ║              ⚠ WARNINGS FOUND                            ║
        echo   ║                                                           ║
        echo   ║   System should work but check warnings above            ║
        echo   ║                                                           ║
        echo   ╚═══════════════════════════════════════════════════════════╝
        echo.
        echo   Warnings: %WARNINGS%
        echo.
        echo   The recompiler might still work, but for best results,
        echo   address the warnings listed above.
        echo.
    )
) else (
    echo   ╔═══════════════════════════════════════════════════════════╗
    echo   ║                                                           ║
    echo   ║              ✗ ERRORS FOUND                              ║
    echo   ║                                                           ║
    echo   ║   Please fix the errors above before using               ║
    echo   ║                                                           ║
    echo   ╚═══════════════════════════════════════════════════════════╝
    echo.
    echo   Errors: %ERRORS%
    echo   Warnings: %WARNINGS%
    echo.
    echo   The recompiler will NOT work until these are fixed.
    echo   See SETUP.md for detailed installation instructions.
    echo.
)

echo ═══════════════════════════════════════════════════════════════
echo.

REM Detailed help for common issues
if %ERRORS% GTR 0 (
    echo NEED HELP?
    echo.
    echo • Python not found?
    echo   Download: https://www.python.org/downloads/
    echo   During install, check: "Add Python to PATH"
    echo.
    echo • No C compiler?
    echo   Option 1 ^(Easiest^): Install MinGW via MSYS2
    echo            https://www.msys2.org/
    echo   Option 2: Install Visual Studio Community
    echo            https://visualstudio.microsoft.com/
    echo.
    echo • Capstone not installed?
    echo   Run: pip install capstone
    echo.
    echo See SETUP.md for complete step-by-step instructions.
    echo.
)

pause
