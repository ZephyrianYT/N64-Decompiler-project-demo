/*
 * BanjoRecomp.cpp
 * Windows Drag-and-Drop Wrapper for N64 Recompiler
 * 
 * Compile with:
 *   cl BanjoRecomp.cpp /Fe:BanjoRecomp.exe /link /SUBSYSTEM:WINDOWS user32.lib shell32.lib
 *   OR
 *   g++ BanjoRecomp.cpp -o BanjoRecomp.exe -mwindows -luser32 -lshell32
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <shlwapi.h>
#include <string>
#include <sstream>

#pragma comment(lib, "user32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "shlwapi.lib")

// Get the directory where this executable is located
std::wstring GetExeDirectory() {
    wchar_t exePath[MAX_PATH];
    GetModuleFileNameW(NULL, exePath, MAX_PATH);
    
    std::wstring path(exePath);
    size_t lastSlash = path.find_last_of(L"\\/");
    if (lastSlash != std::wstring::npos) {
        return path.substr(0, lastSlash);
    }
    return L".";
}

// Show error message box
void ShowError(const wchar_t* title, const wchar_t* message) {
    MessageBoxW(NULL, message, title, MB_OK | MB_ICONERROR);
}

// Show info message box
void ShowInfo(const wchar_t* title, const wchar_t* message) {
    MessageBoxW(NULL, message, title, MB_OK | MB_ICONINFORMATION);
}

// Check if file exists
bool FileExists(const std::wstring& path) {
    DWORD attrib = GetFileAttributesW(path.c_str());
    return (attrib != INVALID_FILE_ATTRIBUTES && !(attrib & FILE_ATTRIBUTE_DIRECTORY));
}

// Main entry point for Windows GUI application
int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPWSTR lpCmdLine, int nCmdShow) {
    // Get command line arguments
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    
    if (argv == NULL) {
        ShowError(L"BanjoRecomp Error", L"Failed to parse command line arguments");
        return 1;
    }
    
    // Check if ROM file was provided
    if (argc < 2) {
        // No file dragged - show usage instructions
        const wchar_t* message = 
            L"Banjo-Kazooie N64 Recompiler\n\n"
            L"USAGE:\n"
            L"  1. Drag and drop your Banjo-Kazooie ROM (.z64 file) onto BanjoRecomp.exe\n"
            L"  2. Wait for the recompilation process to complete\n"
            L"  3. Find the output on your Desktop\n\n"
            L"REQUIREMENTS:\n"
            L"  • Banjo-Kazooie (US 1.0) ROM file\n"
            L"  • Python 3.8 or later installed\n"
            L"  • GCC, Clang, or Visual Studio C compiler\n\n"
            L"NOTES:\n"
            L"  • This is a demonstration implementation\n"
            L"  • For a complete playable port, see:\n"
            L"    https://github.com/BanjoRecomp/BanjoRecomp";
        
        ShowInfo(L"Banjo-Kazooie Recompiler", message);
        
        LocalFree(argv);
        return 0;
    }
    
    // Get ROM file path from command line
    std::wstring romPath = argv[1];
    
    // Verify ROM file exists
    if (!FileExists(romPath)) {
        std::wstringstream errorMsg;
        errorMsg << L"ROM file not found:\n\n" << romPath;
        ShowError(L"File Not Found", errorMsg.str().c_str());
        
        LocalFree(argv);
        return 1;
    }
    
    // Verify it's a .z64 file
    std::wstring extension = PathFindExtensionW(romPath.c_str());
    std::transform(extension.begin(), extension.end(), extension.begin(), ::towlower);
    
    if (extension != L".z64" && extension != L".n64" && extension != L".v64") {
        std::wstringstream errorMsg;
        errorMsg << L"Invalid file type. Expected .z64, .n64, or .v64 file.\n\n"
                 << L"File: " << romPath;
        ShowError(L"Invalid File Type", errorMsg.str().c_str());
        
        LocalFree(argv);
        return 1;
    }
    
    // Get script directory and PowerShell script path
    std::wstring exeDir = GetExeDirectory();
    std::wstring scriptPath = exeDir + L"\\BanjoRecomp.ps1";
    
    // Verify PowerShell script exists
    if (!FileExists(scriptPath)) {
        std::wstringstream errorMsg;
        errorMsg << L"BanjoRecomp.ps1 not found!\n\n"
                 << L"Expected location:\n" << scriptPath << L"\n\n"
                 << L"Please ensure BanjoRecomp.ps1 is in the same folder as BanjoRecomp.exe";
        ShowError(L"Script Not Found", errorMsg.str().c_str());
        
        LocalFree(argv);
        return 1;
    }
    
    // Build PowerShell command
    // We use -ExecutionPolicy Bypass to allow the script to run
    // even if the system's execution policy is restrictive
    std::wstringstream psCommand;
    psCommand << L"powershell.exe -NoProfile -ExecutionPolicy Bypass -File \""
              << scriptPath << L"\" \""
              << romPath << L"\"";
    
    // Create process to run PowerShell script
    STARTUPINFOW si = {0};
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_SHOW;  // Show the PowerShell window
    
    PROCESS_INFORMATION pi = {0};
    
    // Allocate buffer for command (CreateProcessW may modify it)
    std::wstring commandStr = psCommand.str();
    std::vector<wchar_t> commandBuf(commandStr.begin(), commandStr.end());
    commandBuf.push_back(L'\0');
    
    // Launch PowerShell
    BOOL result = CreateProcessW(
        NULL,                   // Application name (use command line)
        &commandBuf[0],        // Command line
        NULL,                   // Process security attributes
        NULL,                   // Thread security attributes
        FALSE,                  // Inherit handles
        CREATE_NEW_CONSOLE,     // Creation flags - new console window
        NULL,                   // Environment
        exeDir.c_str(),        // Current directory
        &si,                    // Startup info
        &pi                     // Process info
    );
    
    if (!result) {
        DWORD error = GetLastError();
        std::wstringstream errorMsg;
        errorMsg << L"Failed to launch PowerShell script.\n\n"
                 << L"Error code: " << error << L"\n\n"
                 << L"Command:\n" << psCommand.str();
        ShowError(L"Launch Failed", errorMsg.str().c_str());
        
        LocalFree(argv);
        return 1;
    }
    
    // Wait for PowerShell process to complete
    WaitForSingleObject(pi.hProcess, INFINITE);
    
    // Get exit code
    DWORD exitCode = 0;
    GetExitCodeProcess(pi.hProcess, &exitCode);
    
    // Clean up
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    LocalFree(argv);
    
    return exitCode;
}
