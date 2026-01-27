(Concept Project for Engineers)
# Banjo-Kazooie N64 Recompiler
## Drag & Drop Edition for Windows 11

A streamlined, user-friendly N64 recompiler specifically designed for Banjo-Kazooie. Simply drag your ROM onto the executable and get a recompiled version on your Desktop.

---

## 🎮 Quick Start

### Requirements

1. **Windows 11** (or Windows 10)
2. **Python 3.8+** - [Download here](https://www.python.org/downloads/)
   - ⚠️ During installation, check "Add Python to PATH"
3. **C Compiler** - One of:
   - **GCC** (Recommended) - Install via [MinGW-w64](https://www.mingw-w64.org/) or [MSYS2](https://www.msys2.org/)
   - **Visual Studio** - [Community Edition is free](https://visualstudio.microsoft.com/)
   - **Clang/LLVM** - [Download here](https://releases.llvm.org/)
4. **Banjo-Kazooie ROM** (US 1.0 version)
   - Game ID: NBKE
   - You must own the original game

### Setup (One-Time)

1. **Extract this package** to a permanent location (e.g., `C:\BanjoRecomp\`)

2. **Build the executable:**
   - Open a terminal in this folder
   - Run: `compile.bat`
   - This creates `BanjoRecomp.exe`

3. **Install Python dependencies:**
   ```bash
   python -m pip install capstone
   ```

### Usage

1. **Drag and drop** your Banjo-Kazooie ROM file (`.z64`) onto `BanjoRecomp.exe`
2. **Wait** for the PowerShell window to complete the process
3. **Find your output** on the Desktop in a timestamped folder
4. **Run** `BanjoKazooie-Recompiled.exe` from the output folder

---

## 📁 Project Structure

```
BanjoRecomp/
├── BanjoRecomp.exe         # Drag-and-drop wrapper (you create this)
├── BanjoRecomp.cpp         # C++ source for wrapper
├── BanjoRecomp.ps1         # Main recompilation script
├── compile.bat             # Helper to build the .exe
├── README.md               # This file
└── [Output on Desktop]/    # Generated after first run
    ├── BanjoKazooie-Recompiled.exe
    └── work/               # Intermediate files
        ├── segments/       # Extracted ROM sections
        ├── asm/            # Disassembled MIPS code
        ├── generated/      # Generated C code
        └── runtime/        # N64 runtime implementation
```

---

## 🔧 How It Works

This recompiler follows a clean, automated pipeline:

### Pipeline Stages

1. **ROM Validation** - Verifies the ROM is Banjo-Kazooie (US 1.0)
2. **Tool Initialization** - Checks Python, compilers, and installs dependencies
3. **ROM Extraction** - Extracts code and data segments from the ROM
4. **Disassembly** - Converts MIPS machine code to assembly using Capstone
5. **Code Generation** - Translates MIPS assembly to C code (stubs in demo)
6. **Runtime Creation** - Generates N64 emulation runtime (memory, CPU state)
7. **Compilation** - Compiles everything into a Windows executable

### Technology Stack

- **PowerShell** - Orchestration and workflow management
- **Python** - Disassembly and code generation
- **Capstone** - MIPS disassembler engine
- **C/C++** - Final executable compilation
- **Windows APIs** - Drag-and-drop interface

---

## ⚙️ Configuration

### ROM Details (BanjoRecomp.ps1)

```powershell
ExpectedGameID = "NBKE"              # Must match
ExpectedTitle = "Banjo-Kazooie"      # Expected title
ExpectedSHA1 = "d6133ace..."         # US 1.0 hash (warning if mismatch)
```

### Output Settings

```powershell
DesktopOutput = [Environment]::GetFolderPath("Desktop")
OutputName = "BanjoKazooie-Recompiled"
CreateTimestamp = $true              # Adds timestamp to folder name
```

---

## 🛠️ For Developers

### Adapting for Other ROMs

This architecture is designed to be easily adaptable for other N64 games. To adapt:

1. **Update ROM configuration** in `BanjoRecomp.ps1`:
   ```powershell
   ExpectedGameID = "XXXX"          # New game ID
   ExpectedTitle = "Game Name"      # New title
   EntryPoint = 0xXXXXXXXX         # Entry point from ROM header
   ```

2. **Update segment extraction** in `Invoke-ROMExtraction`:
   ```powershell
   $segments = @(
       @{ Name = "boot"; Start = 0x40; End = 0x1000; ... },
       @{ Name = "code"; Start = 0x1000; End = 0x...; ... }
   )
   ```

3. **Rename the script and wrapper**:
   - `BanjoRecomp.ps1` → `GameRecomp.ps1`
   - Update `BanjoRecomp.cpp` script path reference
   - Recompile wrapper

### Building from Source

```bash
# Using Visual Studio C++ compiler
cl BanjoRecomp.cpp /Fe:BanjoRecomp.exe /link /SUBSYSTEM:WINDOWS user32.lib shell32.lib

# Using MinGW/GCC
g++ BanjoRecomp.cpp -o BanjoRecomp.exe -mwindows -luser32 -lshell32 -static

# Using Clang
clang++ BanjoRecomp.cpp -o BanjoRecomp.exe -mwindows -luser32 -lshell32
```

### PowerShell Script Testing

```powershell
# Run directly without wrapper
.\BanjoRecomp.ps1 "path\to\rom.z64"

# Enable verbose output
$VerbosePreference = "Continue"
.\BanjoRecomp.ps1 "path\to\rom.z64"
```

---

## 📋 Features

✅ **Simple UX** - Drag and drop, that's it
✅ **Automatic** - No config files, no manual steps
✅ **Redundant** - Multiple compiler support, error handling
✅ **Accurate** - ROM validation, proper N64 memory model
✅ **Portable** - Self-contained, no installation required
✅ **Adaptable** - Easy to modify for other N64 games
✅ **Clean Output** - Everything organized on Desktop

---

## ⚠️ Important Notes

### This is a DEMONSTRATION

This implementation is a **proof-of-concept** showing the clean architecture approach. It generates stub C code rather than full MIPS→C translation.

**For a complete, playable Banjo-Kazooie recompilation**, see:
- **BanjoRecomp**: https://github.com/BanjoRecomp/BanjoRecomp

### What This Demo Does

✅ Validates ROM
✅ Extracts segments
✅ Disassembles MIPS code
✅ Generates C function stubs
✅ Compiles to Windows executable
✅ Creates N64 runtime framework

### What's Needed for Full Recompilation

❌ Complete MIPS→C instruction translation
❌ Function signature detection
❌ Register allocation
❌ Memory access patterns
❌ Graphics/Audio/Controller emulation
❌ Asset extraction and loading

### Path to Full Implementation

To make this a complete recompiler:

1. **Reference BanjoRecomp's approach**:
   - Study their TOML configuration structure
   - Examine their N64Recomp tool usage
   - Review their runtime implementation

2. **Implement proper MIPS translation**:
   - Use rabbitizer for instruction decoding
   - Generate proper C translations per instruction
   - Handle function calls and returns correctly
   - Implement register preservation

3. **Add full runtime**:
   - N64 memory management
   - RSP (audio/graphics coprocessor)
   - Controller input
   - Save state support

4. **Integrate with N64Recomp**:
   - Use official N64Recomp tool instead of custom Python
   - Follow their established patterns
   - Contribute improvements back

---

## 🔗 References

- **BanjoRecomp Project**: https://github.com/BanjoRecomp/BanjoRecomp
- **N64Recomp Tool**: https://github.com/N64Recomp/N64Recomp
- **Banjo-Kazooie Decomp**: https://github.com/Mr-Wiseguy/banjo-kazooie
- **Capstone**: https://www.capstone-engine.org/

---

## 📝 License

This is educational/demonstration software. Ensure you own the original Banjo-Kazooie game before using this tool.

The recompilation approach is based on the excellent work by:
- N64Recomp authors
- BanjoRecomp team
- Banjo-Kazooie decompilation project

---

## 🐛 Troubleshooting

### "Python not found"
- Install Python from python.org
- Make sure "Add to PATH" was checked during installation
- Restart your terminal/computer

### "Compiler not found"
- Install MinGW-w64, Visual Studio, or LLVM
- Make sure the compiler is in your PATH
- Try running `gcc --version` or `cl` to verify

### "Capstone not installed"
```bash
python -m pip install capstone
```

### "ROM validation failed"
- Ensure you have the US 1.0 version (Game ID: NBKE)
- Check the ROM file isn't corrupted
- The tool will warn but proceed with other versions

### PowerShell execution policy error
The wrapper uses `-ExecutionPolicy Bypass` to avoid this, but if you run the script directly:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 💡 Tips

- **Keep your ROM in a simple path** (no spaces, special characters)
- **Close other programs** during compilation to speed up the process
- **Check the work folder** to examine intermediate files
- **Read PowerShell output** for detailed progress information
- **Check Desktop for output** - it creates a timestamped folder

---

Created with the Clean Architecture approach for N64 recompilation.
Designed for simplicity, accuracy, and easy adaptation to other N64 titles.
