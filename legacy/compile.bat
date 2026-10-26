@echo off
REM BanjoRecomp Compiler Script
REM Attempts to compile BanjoRecomp.cpp using available compilers

echo.
echo ===================================================================
echo   Banjo-Kazooie Recompiler - Building Drag and Drop Wrapper
echo ===================================================================
echo.

REM Check if source file exists
if not exist "BanjoRecomp.cpp" (
    echo ERROR: BanjoRecomp.cpp not found!
    echo Please ensure you're running this from the correct directory.
    pause
    exit /b 1
)

REM Try MSVC first (Visual Studio)
where cl.exe >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo Found: Microsoft Visual C++ Compiler
    echo Compiling with MSVC...
    echo.
    
    cl.exe BanjoRecomp.cpp /Fe:BanjoRecomp.exe /link /SUBSYSTEM:WINDOWS user32.lib shell32.lib shlwapi.lib
    
    if exist "BanjoRecomp.exe" (
        echo.
        echo ===================================================================
        echo   SUCCESS! BanjoRecomp.exe has been created.
        echo ===================================================================
        echo.
        echo Cleaning up object files...
        del BanjoRecomp.obj >nul 2>&1
        echo.
        echo You can now drag and drop your Banjo-Kazooie ROM onto BanjoRecomp.exe
        echo.
        pause
        exit /b 0
    ) else (
        echo.
        echo Compilation failed. Check errors above.
        pause
        exit /b 1
    )
)

REM Try GCC (MinGW)
where g++.exe >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo Found: GCC/MinGW Compiler
    echo Compiling with GCC...
    echo.
    
    g++.exe BanjoRecomp.cpp -o BanjoRecomp.exe -mwindows -luser32 -lshell32 -lshlwapi -static
    
    if exist "BanjoRecomp.exe" (
        echo.
        echo ===================================================================
        echo   SUCCESS! BanjoRecomp.exe has been created.
        echo ===================================================================
        echo.
        echo You can now drag and drop your Banjo-Kazooie ROM onto BanjoRecomp.exe
        echo.
        pause
        exit /b 0
    ) else (
        echo.
        echo Compilation failed. Check errors above.
        pause
        exit /b 1
    )
)

REM Try Clang
where clang++.exe >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo Found: Clang Compiler
    echo Compiling with Clang...
    echo.
    
    clang++.exe BanjoRecomp.cpp -o BanjoRecomp.exe -mwindows -luser32 -lshell32 -lshlwapi
    
    if exist "BanjoRecomp.exe" (
        echo.
        echo ===================================================================
        echo   SUCCESS! BanjoRecomp.exe has been created.
        echo ===================================================================
        echo.
        echo You can now drag and drop your Banjo-Kazooie ROM onto BanjoRecomp.exe
        echo.
        pause
        exit /b 0
    ) else (
        echo.
        echo Compilation failed. Check errors above.
        pause
        exit /b 1
    )
)

REM No compiler found
echo.
echo ===================================================================
echo   ERROR: No C++ compiler found!
echo ===================================================================
echo.
echo This script tried to find:
echo   - Microsoft Visual C++ (cl.exe)
echo   - GCC/MinGW (g++.exe)
echo   - Clang (clang++.exe)
echo.
echo Please install one of the following:
echo.
echo   1. Visual Studio Community (free)
echo      https://visualstudio.microsoft.com/
echo.
echo   2. MinGW-w64 (recommended for beginners)
echo      https://www.mingw-w64.org/
echo      OR use MSYS2: https://www.msys2.org/
echo.
echo   3. LLVM/Clang
echo      https://releases.llvm.org/
echo.
echo After installation, make sure the compiler is in your PATH,
echo then run this script again.
echo.
pause
exit /b 1
