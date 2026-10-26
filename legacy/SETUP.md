# Setup Guide for Banjo-Kazooie Recompiler
## Windows 11 - First Time Setup

This guide will walk you through setting up the Banjo-Kazooie recompiler from scratch.

---

## 📋 Prerequisites Checklist

Before starting, you'll need:

- [ ] Windows 11 (or Windows 10)
- [ ] Administrator access
- [ ] Internet connection
- [ ] ~2GB free disk space
- [ ] Banjo-Kazooie ROM file (US 1.0)

---

## 🔧 Step-by-Step Setup

### 1. Install Python

Python is required for the disassembly and code generation steps.

#### Download Python
1. Go to: https://www.python.org/downloads/
2. Click "Download Python 3.x.x" (latest version)
3. Run the installer

#### Installation Options
⚠️ **CRITICAL**: Check these boxes during installation:
- [x] **Add python.exe to PATH** ← Very important!
- [x] Install pip
- [x] Install for all users (optional)

#### Verify Installation
```bash
# Open PowerShell or Command Prompt
python --version
# Should output: Python 3.x.x

pip --version
# Should output: pip 23.x.x from...
```

---

### 2. Install a C Compiler

You need a C compiler to build the final executable. Choose ONE:

#### Option A: MinGW-w64 (Recommended for Beginners)

**Easiest method - Using MSYS2:**

1. Download MSYS2: https://www.msys2.org/
2. Run the installer (use default location: `C:\msys64\`)
3. Open "MSYS2 MSYS" from Start menu
4. Run these commands:
   ```bash
   pacman -Syu
   # Close and reopen MSYS2
   pacman -S mingw-w64-x86_64-gcc
   ```

5. Add to Windows PATH:
   - Search for "Environment Variables" in Windows
   - Edit "Path" in System variables
   - Add: `C:\msys64\mingw64\bin`
   - Click OK

6. Verify:
   ```bash
   # Open NEW Command Prompt
   gcc --version
   # Should show gcc version info
   ```

#### Option B: Visual Studio (Microsoft's Compiler)

1. Download Visual Studio Community: https://visualstudio.microsoft.com/
2. Run installer
3. Select "Desktop development with C++"
4. Install (requires ~6GB)

5. Setup Developer Command Prompt:
   - Search for "Developer Command Prompt for VS" in Start menu
   - Use this terminal for compiling

#### Option C: LLVM/Clang

1. Download LLVM: https://releases.llvm.org/
2. Get the Windows installer (.exe)
3. During install, check "Add LLVM to system PATH"
4. Verify:
   ```bash
   clang --version
   ```

---

### 3. Install Python Dependencies

```bash
# Open Command Prompt or PowerShell
python -m pip install --upgrade pip
python -m pip install capstone
```

**Capstone** is the MIPS disassembler library.

Verify:
```bash
python -c "import capstone; print('Capstone OK')"
# Should output: Capstone OK
```

---

### 4. Setup BanjoRecomp

#### Extract Package
1. Extract the BanjoRecomp package to a permanent location
2. Recommended: `C:\BanjoRecomp\`
3. **DO NOT** use folders with spaces in the name

#### Build the Wrapper
```bash
# Open Command Prompt in BanjoRecomp folder
cd C:\BanjoRecomp

# Run the build script
compile.bat
```

This should create `BanjoRecomp.exe`.

---

### 5. Prepare Your ROM

#### ROM Requirements
- **Game**: Banjo-Kazooie
- **Region**: NTSC-U (North America)
- **Version**: 1.0
- **Format**: `.z64` (big-endian)
- **Game ID**: NBKE
- **Size**: 16 MB (16,777,216 bytes)

#### Verify Your ROM
Right-click the ROM → Properties → Details

- **Game Title should contain**: "Banjo-Kazooie"
- **Size**: ~16 MB

#### Convert ROM Format (if needed)

If you have `.n64` or `.v64` format:

```bash
# Using Tool64
Tool64.exe yourrom.n64 yourrom.z64
```

Or use an online converter.

---

## 🚀 Testing Your Setup

### Quick Test

1. Copy your Banjo-Kazooie ROM to a simple location:
   ```
   C:\Temp\BanjoKazooie.z64
   ```

2. Drag `BanjoKazooie.z64` onto `BanjoRecomp.exe`

3. A PowerShell window should appear showing:
   ```
   ╔═══════════════════════════════════════════════════════╗
   ║      N64 RECOMPILER - BANJO-KAZOOIE EDITION          ║
   ║             Drag & Drop Recompilation                 ║
   ╚═══════════════════════════════════════════════════════╝
   
   [1/7] Validating Banjo-Kazooie ROM...
   ```

4. Wait for completion (2-5 minutes)

5. Check your Desktop for:
   ```
   Desktop/
   └── BanjoKazooie-Recompiled_YYYYMMDD_HHMMSS/
       ├── BanjoKazooie-Recompiled.exe
       └── work/
   ```

6. Run the executable to verify it works

---

## 🐛 Troubleshooting Setup Issues

### "Python not recognized"

**Problem**: Windows can't find Python

**Solution**:
1. Uninstall Python
2. Reinstall, making sure to check "Add Python to PATH"
3. Restart computer
4. Try again

**Manual PATH fix**:
1. Find Python install location (usually `C:\Python3x\`)
2. Add to PATH:
   - Win + R → `sysdm.cpl` → Advanced → Environment Variables
   - Edit "Path"
   - Add Python folder
   - Add Python Scripts folder

### "gcc/cl not recognized"

**Problem**: Compiler not in PATH

**Solution for MinGW**:
```
Add to PATH: C:\msys64\mingw64\bin
```

**Solution for Visual Studio**:
Use "Developer Command Prompt for VS" instead of regular Command Prompt

### "Access denied" when running compile.bat

**Problem**: Need admin rights

**Solution**:
Right-click `compile.bat` → "Run as administrator"

### Capstone import error

```bash
# Force reinstall
python -m pip uninstall capstone
python -m pip install capstone --no-cache-dir
```

### "PowerShell script not digitally signed"

The wrapper uses `-ExecutionPolicy Bypass` to avoid this.

If you run the script directly:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Build succeeds but exe doesn't run

**Check these**:
1. Are you using 64-bit Python? (required)
2. Is antivirus blocking it?
3. Try running from Command Prompt to see errors

---

## 📁 File Organization Tips

### Recommended Folder Structure

```
C:\
├── BanjoRecomp\              # The recompiler
│   ├── BanjoRecomp.exe
│   ├── BanjoRecomp.ps1
│   ├── BanjoRecomp.cpp
│   └── ...
│
├── ROMs\                      # Your ROM collection
│   ├── BanjoKazooie.z64
│   ├── BanjoTooie.z64
│   └── ...
│
└── Users\YourName\Desktop\    # Output goes here
    └── BanjoKazooie-Recompiled_*/
```

### Keeping It Clean

- Don't mix ROM files with the recompiler files
- The tool creates timestamped folders - you can delete old ones
- Work files are in the output folder - safe to delete after testing

---

## 🎯 Next Steps

After successful setup:

1. **Read README.md** for detailed usage instructions
2. **Try recompiling** your Banjo-Kazooie ROM
3. **Explore the output** folder to understand the process
4. **Check the work folder** to see intermediate files
5. **Adapt for other ROMs** if you're a developer

---

## 📞 Getting Help

### Check These First
1. README.md - Main documentation
2. This file - Setup issues
3. PowerShell output - Error messages are descriptive

### Common Questions

**Q: How long does recompilation take?**
A: 2-5 minutes for the demo, depending on your PC.

**Q: Can I recompile other N64 games?**
A: Yes! See README.md "For Developers" section on adapting the tool.

**Q: Why is the output on Desktop?**
A: Easy to find. You can change this in BanjoRecomp.ps1.

**Q: Is this legal?**
A: You must own the original Banjo-Kazooie game. This tool doesn't distribute ROMs.

**Q: Will this run the actual game?**
A: This demo creates a framework. For a playable version, see BanjoRecomp on GitHub.

---

## 🎓 Understanding the Process

### What Happens When You Drag the ROM?

1. **Wrapper (BanjoRecomp.exe)** catches the drop
2. **PowerShell script (BanjoRecomp.ps1)** runs
3. **ROM validation** checks it's Banjo-Kazooie
4. **Python scripts** disassemble MIPS code
5. **C generation** creates PC-compatible code
6. **Compiler** builds the final executable
7. **Output** appears on your Desktop

### Why These Tools?

- **Python**: Easy scripting, great libraries (Capstone)
- **PowerShell**: Native Windows, good orchestration
- **Capstone**: Industry-standard disassembler
- **C compiler**: Creates fast, native Windows executables

---

## ✅ Setup Complete!

If you've followed all steps and tests pass, you're ready to use the recompiler.

**Happy recompiling!** 🎮

---

_Setup Guide v1.0 - Clean Architecture Edition_
