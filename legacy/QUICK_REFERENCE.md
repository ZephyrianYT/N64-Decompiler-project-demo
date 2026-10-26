# Banjo-Kazooie Recompiler - Quick Reference

## 🎮 QUICK START (3 Steps)

1. **Setup** (one time only):
   ```
   - Install Python 3.8+
   - Install a C compiler (GCC/MSVC/Clang)
   - Run: compile.bat
   - Run: pip install capstone
   ```

2. **Use**:
   ```
   Drag BanjoKazooie.z64 onto BanjoRecomp.exe
   ```

3. **Find**:
   ```
   Check Desktop for: BanjoKazooie-Recompiled_*/
   ```

---

## 📁 Files Explained

| File | Purpose |
|------|---------|
| `BanjoRecomp.exe` | Drag ROM here → Magic happens |
| `BanjoRecomp.ps1` | Main recompilation script |
| `BanjoRecomp.cpp` | Source for wrapper (for building) |
| `compile.bat` | Builds the .exe from .cpp |
| `gamedb.json` | ROM configuration database |
| `README.md` | Full documentation |
| `SETUP.md` | First-time setup guide |

---

## 🔧 Commands

### Build the wrapper:
```batch
compile.bat
```

### Run script directly (without wrapper):
```powershell
.\BanjoRecomp.ps1 "path\to\rom.z64"
```

### Install Python dependencies:
```bash
pip install capstone
```

### Test Python:
```bash
python --version
python -c "import capstone; print('OK')"
```

### Test compiler:
```bash
gcc --version     # GCC/MinGW
cl                # MSVC (in Developer Command Prompt)
clang --version   # Clang
```

---

## ⚙️ Configuration (BanjoRecomp.ps1)

### Change output location:
```powershell
Line 20: DesktopOutput = "C:\MyFolder"
```

### Disable timestamp in folder name:
```powershell
Line 31: CreateTimestamp = $false
```

### Change output exe name:
```powershell
Line 30: OutputName = "MyGameName"
```

---

## 🐛 Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| "Python not found" | Install Python, check "Add to PATH" |
| "Compiler not found" | Install GCC/MSVC/Clang, add to PATH |
| "Capstone not installed" | `pip install capstone` |
| ROM validation fails | Check you have US 1.0 version (NBKE) |
| Exe won't run | Check antivirus, run from command prompt |
| PowerShell error | Right-click BanjoRecomp.ps1 → Run with PowerShell |

---

## 📊 Expected Output Structure

```
Desktop/
└── BanjoKazooie-Recompiled_20260127_143022/
    ├── BanjoKazooie-Recompiled.exe    ← Run this!
    └── work/
        ├── segments/                   ← Extracted ROM data
        ├── asm/                        ← Disassembled code
        ├── generated/                  ← Generated C files
        └── runtime/                    ← N64 runtime
```

---

## 🎯 ROM Requirements

- **Name**: Banjo-Kazooie
- **Region**: US (NTSC-U)
- **Version**: 1.0
- **Game ID**: NBKE
- **Format**: .z64 (big-endian)
- **Size**: 16 MB

---

## 🚀 Performance

- **Time**: 2-5 minutes (demo version)
- **Disk**: ~500MB for output
- **RAM**: 4GB recommended
- **CPU**: Any modern CPU

---

## 📝 For Developers

### Adapt for another N64 game:

1. Edit `BanjoRecomp.ps1` lines 17-25:
   ```powershell
   ExpectedGameID = "XXXX"
   ExpectedTitle = "Game Name"
   EntryPoint = 0xXXXXXXXX
   ```

2. Update segment extraction (line 353+)

3. Rename files

4. Recompile wrapper

---

## 🔗 Links

- **Full Banjo Port**: https://github.com/BanjoRecomp/BanjoRecomp
- **N64Recomp Tool**: https://github.com/N64Recomp/N64Recomp
- **Decomp Project**: https://github.com/Mr-Wiseguy/banjo-kazooie

---

## ⚠️ Important Notes

### This is a DEMO
- Generates stub code, not full translation
- For playable version, see BanjoRecomp GitHub
- Shows the clean architecture approach

### You MUST own Banjo-Kazooie
- This tool requires a legal ROM dump
- Do not distribute ROMs
- Support the developers!

---

## 💡 Tips

✓ Use simple paths (no spaces)
✓ Keep ROM in accessible location
✓ Check Desktop for output
✓ Read PowerShell output for details
✓ Delete old timestamped folders
✓ Work folder shows intermediate steps

---

**Made with the Clean Architecture philosophy**
**Designed for simplicity, redundancy, and accuracy**

_v1.0 - Windows 11 Drag & Drop Edition_
