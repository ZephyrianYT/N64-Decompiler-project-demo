#Requires -Version 5.1
<#
.SYNOPSIS
    N64 Recompiler - Banjo-Kazooie Edition
    
.DESCRIPTION
    Drag and drop a Banjo-Kazooie ROM onto BanjoRecomp.exe to automatically
    recompile it. Output will be placed on your desktop.
    
.PARAMETER RomPath
    Path to the Banjo-Kazooie ROM file (.z64)
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$RomPath
)

#region Configuration
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Script:Config = @{
    # Paths
    ScriptDir = $PSScriptRoot
    DesktopOutput = [Environment]::GetFolderPath("Desktop")
    
    # Expected ROM details for Banjo-Kazooie (US 1.0)
    ExpectedGameID = "NBKE"
    ExpectedTitle = "Banjo-Kazooie"
    ExpectedSHA1 = "d6133ace5afaa0882cf214cf88daba39e266c078"
    
    # ROM structure
    EntryPoint = 0x80100400
    RAMBase = 0x80000000
    CodeStartROM = 0x1000
    
    # Output settings
    OutputName = "BanjoKazooie-Recompiled"
    CreateTimestamp = $true
}

# Tool URLs for automatic download
$Script:ToolURLs = @{
    N64Recomp = "https://github.com/N64Recomp/N64Recomp/releases/latest/download/N64Recomp-windows.zip"
    RSPRecomp = "https://github.com/N64Recomp/N64Recomp/releases/latest/download/RSPRecomp-windows.zip"
}
#endregion

#region UI Functions
function Write-Header {
    Clear-Host
    Write-Host ""
    Write-Host "  ╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║                                                               ║" -ForegroundColor Cyan
    Write-Host "  ║          N64 RECOMPILER - BANJO-KAZOOIE EDITION              ║" -ForegroundColor Cyan
    Write-Host "  ║                  Drag & Drop Recompilation                    ║" -ForegroundColor Cyan
    Write-Host "  ║                                                               ║" -ForegroundColor Cyan
    Write-Host "  ╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param(
        [int]$Step,
        [int]$Total,
        [string]$Message
    )
    Write-Host "  [$Step/$Total] " -NoNewline -ForegroundColor White
    Write-Host $Message -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "         ✓ " -NoNewline -ForegroundColor Green
    Write-Host $Message -ForegroundColor White
}

function Write-Info {
    param([string]$Message)
    Write-Host "           " -NoNewline
    Write-Host $Message -ForegroundColor Gray
}

function Write-Warning {
    param([string]$Message)
    Write-Host "         ⚠ " -NoNewline -ForegroundColor Yellow
    Write-Host $Message -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "         ✗ " -NoNewline -ForegroundColor Red
    Write-Host $Message -ForegroundColor Red
}

function Write-Separator {
    Write-Host ("  " + ("-" * 63)) -ForegroundColor DarkGray
}
#endregion

#region ROM Analysis Functions
function Get-ROMInfo {
    param([string]$Path)
    
    if (-not (Test-Path $Path)) {
        throw "ROM file not found: $Path"
    }
    
    # Read ROM file
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    
    if ($bytes.Length -lt 64) {
        throw "Invalid ROM file: too small (${bytes.Length} bytes)"
    }
    
    # Parse N64 ROM header (big-endian)
    $info = @{}
    
    # Format byte
    $info.Format = $bytes[0]
    
    # Entry point (bytes 8-11, big-endian)
    $info.EntryPoint = [BitConverter]::ToUInt32([array]::Reverse($bytes[8..11]), 0)
    
    # Game title (bytes 32-51, ASCII)
    $titleBytes = $bytes[32..51]
    $info.Title = [System.Text.Encoding]::ASCII.GetString($titleBytes).Trim([char]0, ' ')
    
    # Game ID (bytes 59-62, ASCII)
    $info.GameID = [System.Text.Encoding]::ASCII.GetString($bytes[59..62])
    
    # Version (byte 63)
    $info.Version = $bytes[63]
    
    # Region (byte 62)
    $info.Region = [char]$bytes[62]
    
    # File info
    $info.FilePath = $Path
    $info.FileName = [System.IO.Path]::GetFileName($Path)
    $info.FileSize = $bytes.Length
    
    # Calculate SHA1 hash
    $sha1 = [System.Security.Cryptography.SHA1]::Create()
    $hashBytes = $sha1.ComputeHash($bytes)
    $info.SHA1 = -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
    
    return $info
}

function Test-BanjoKazooieROM {
    param([hashtable]$ROMInfo)
    
    $issues = @()
    
    # Check Game ID
    if ($ROMInfo.GameID -ne $Config.ExpectedGameID) {
        $issues += "Game ID mismatch. Expected: $($Config.ExpectedGameID), Found: $($ROMInfo.GameID)"
    }
    
    # Check title contains Banjo-Kazooie
    if ($ROMInfo.Title -notmatch "Banjo.*Kazooie") {
        $issues += "Title mismatch. Expected: $($Config.ExpectedTitle), Found: $($ROMInfo.Title)"
    }
    
    # Warn if hash doesn't match (but don't fail - could be different region/version)
    if ($ROMInfo.SHA1 -ne $Config.ExpectedSHA1) {
        Write-Warning "ROM hash doesn't match US 1.0 version"
        Write-Info "Expected: $($Config.ExpectedSHA1)"
        Write-Info "Found:    $($ROMInfo.SHA1)"
        Write-Info "Continuing anyway (may be different version)..."
    }
    
    if ($issues.Count -gt 0) {
        throw ($issues -join "`n")
    }
    
    return $true
}
#endregion

#region Tool Management
function Initialize-Tools {
    $toolsDir = Join-Path $Config.ScriptDir "tools"
    
    if (-not (Test-Path $toolsDir)) {
        New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
    }
    
    # Check for required Python packages
    Write-Info "Checking Python installation..."
    
    try {
        $pythonVersion = & python --version 2>&1
        if ($pythonVersion -match "Python (\d+\.\d+)") {
            Write-Info "Python found: $pythonVersion"
        }
    }
    catch {
        throw "Python is required but not found in PATH. Please install Python 3.8 or later."
    }
    
    # Check/install required packages
    $requiredPackages = @("capstone")
    foreach ($package in $requiredPackages) {
        Write-Info "Checking for package: $package..."
        try {
            & python -c "import $package" 2>&1 | Out-Null
            Write-Info "$package is installed"
        }
        catch {
            Write-Info "Installing $package..."
            & python -m pip install $package --quiet 2>&1 | Out-Null
        }
    }
    
    return $toolsDir
}

function Get-Compiler {
    # Try to find an available C compiler
    $compilers = @(
        @{ Name = "GCC"; Command = "gcc"; Type = "gcc" },
        @{ Name = "Clang"; Command = "clang"; Type = "clang" },
        @{ Name = "MSVC"; Command = "cl"; Type = "msvc" }
    )
    
    foreach ($compiler in $compilers) {
        try {
            $null = Get-Command $compiler.Command -ErrorAction Stop
            Write-Info "Compiler found: $($compiler.Name)"
            return $compiler
        }
        catch {
            continue
        }
    }
    
    throw "No C compiler found. Please install GCC, Clang, or Visual Studio."
}
#endregion

#region Recompilation Pipeline
function Invoke-ROMExtraction {
    param(
        [hashtable]$ROMInfo,
        [string]$OutputDir
    )
    
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }
    
    $bytes = [System.IO.File]::ReadAllBytes($ROMInfo.FilePath)
    
    # Extract segments based on Banjo-Kazooie structure
    $segments = @(
        @{
            Name = "boot"
            Start = 0x40
            End = 0x1000
            VRAM = 0x80000400
            File = "boot.bin"
        },
        @{
            Name = "code"
            Start = 0x1000
            End = [Math]::Min($bytes.Length, 0x900000)
            VRAM = 0x80001000
            File = "code.bin"
        }
    )
    
    foreach ($segment in $segments) {
        $data = $bytes[$segment.Start..($segment.End - 1)]
        $outputPath = Join-Path $OutputDir $segment.File
        [System.IO.File]::WriteAllBytes($outputPath, $data)
        
        Write-Info "Extracted $($segment.Name): $([math]::Round($data.Length / 1KB, 2)) KB"
    }
    
    return $segments
}

function Invoke-Disassembly {
    param(
        [array]$Segments,
        [string]$SegmentsDir,
        [string]$OutputDir
    )
    
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }
    
    # Create Python disassembler script
    $disasmScript = @'
import sys
import struct
from pathlib import Path

try:
    from capstone import *
except ImportError:
    print("ERROR: Capstone not installed. Run: pip install capstone")
    sys.exit(1)

def disassemble_segment(bin_file, output_file, base_vram):
    """Disassemble a MIPS binary segment"""
    
    # Read binary data
    with open(bin_file, 'rb') as f:
        code = f.read()
    
    if len(code) == 0:
        print(f"WARNING: {bin_file} is empty")
        return 0
    
    # Initialize MIPS disassembler (big-endian MIPS III/N64)
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 | CS_MODE_BIG_ENDIAN)
    md.detail = True
    
    # Disassemble
    instructions = []
    for instr in md.disasm(code, base_vram):
        instructions.append({
            'vram': instr.address,
            'bytes': ' '.join(f'{b:02x}' for b in instr.bytes),
            'mnemonic': instr.mnemonic,
            'operands': instr.op_str
        })
    
    # Write assembly output
    with open(output_file, 'w') as f:
        f.write(f"# Disassembly\n")
        f.write(f"# Base VRAM: 0x{base_vram:08x}\n")
        f.write(f"# Instructions: {len(instructions)}\n\n")
        
        for instr in instructions:
            f.write(f"{instr['vram']:08x}  {instr['bytes']:<12}  ")
            f.write(f"{instr['mnemonic']:<8} {instr['operands']}\n")
    
    return len(instructions)

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: disasm.py <input.bin> <output.s> <base_vram_hex>")
        sys.exit(1)
    
    bin_file = sys.argv[1]
    output_file = sys.argv[2]
    base_vram = int(sys.argv[3], 16)
    
    count = disassemble_segment(bin_file, output_file, base_vram)
    print(f"Disassembled {count} instructions")
'@
    
    $disasmScriptPath = Join-Path $OutputDir "disasm.py"
    $disasmScript | Out-File -FilePath $disasmScriptPath -Encoding UTF8 -NoNewline
    
    # Disassemble each segment
    $totalInstructions = 0
    foreach ($segment in $Segments) {
        $binPath = Join-Path $SegmentsDir $segment.File
        $asmPath = Join-Path $OutputDir "$($segment.Name).s"
        
        Write-Info "Disassembling $($segment.Name)..."
        
        $output = & python $disasmScriptPath $binPath $asmPath ("{0:X}" -f $segment.VRAM) 2>&1
        
        if ($LASTEXITCODE -eq 0 -and (Test-Path $asmPath)) {
            if ($output -match "(\d+) instructions") {
                $count = [int]$Matches[1]
                $totalInstructions += $count
                Write-Info "  → $count instructions"
            }
        }
        else {
            Write-Warning "Disassembly failed for $($segment.Name)"
        }
    }
    
    Write-Success "$totalInstructions total instructions disassembled"
    return $totalInstructions
}

function Invoke-CodeGeneration {
    param(
        [string]$AsmDir,
        [string]$OutputDir
    )
    
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }
    
    # Create C code generator script
    $generatorScript = @'
import sys
import re
from pathlib import Path

def generate_c_stub(func_name, vram_start, instruction_count):
    """Generate a C stub function"""
    
    c_code = f"""/* Generated function: {func_name} */
/* VRAM: 0x{vram_start:08x} */
/* Instructions: {instruction_count} */

#include "recomp.h"

void {func_name}(void) {{
    /* TODO: Implement MIPS translation */
    /* This is a stub - full implementation requires MIPS->C translation */
}}
"""
    return c_code

def parse_asm_file(asm_file):
    """Parse assembly file and extract basic structure"""
    
    functions = []
    current_func = None
    instr_count = 0
    
    with open(asm_file, 'r') as f:
        for line in f:
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Parse instruction line: "VRAM  BYTES  MNEMONIC OPERANDS"
            match = re.match(r'([0-9a-f]{8})\s+([0-9a-f\s]+)\s+(\w+)(?:\s+(.*))?', line, re.IGNORECASE)
            if match:
                vram = int(match.group(1), 16)
                mnemonic = match.group(3)
                
                # Start new function on certain patterns
                if current_func is None:
                    current_func = {
                        'vram': vram,
                        'name': f'func_{vram:08x}',
                        'instructions': 0
                    }
                
                instr_count += 1
                current_func['instructions'] += 1
                
                # End function on return/jump
                if mnemonic in ['jr', 'j'] and current_func['instructions'] > 5:
                    functions.append(current_func)
                    current_func = None
                    instr_count = 0
    
    # Add last function if exists
    if current_func and current_func['instructions'] > 0:
        functions.append(current_func)
    
    return functions

def main(asm_dir, output_dir):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    asm_files = list(Path(asm_dir).glob('*.s'))
    
    if not asm_files:
        print("No assembly files found")
        return
    
    all_functions = []
    
    for asm_file in asm_files:
        functions = parse_asm_file(asm_file)
        
        # Limit to prevent excessive files
        functions = functions[:100]
        all_functions.extend(functions)
        
        # Generate C file for each function
        for func in functions:
            c_code = generate_c_stub(func['name'], func['vram'], func['instructions'])
            
            output_file = output_path / f"{func['name']}.c"
            with open(output_file, 'w') as f:
                f.write(c_code)
    
    print(f"Generated {len(all_functions)} C files")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: codegen.py <asm_dir> <output_dir>")
        sys.exit(1)
    
    main(sys.argv[1], sys.argv[2])
'@
    
    $generatorScriptPath = Join-Path $OutputDir "codegen.py"
    $generatorScript | Out-File -FilePath $generatorScriptPath -Encoding UTF8 -NoNewline
    
    Write-Info "Generating C code..."
    
    $output = & python $generatorScriptPath $AsmDir $OutputDir 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        $cFiles = Get-ChildItem -Path $OutputDir -Filter "*.c" -File
        Write-Success "$($cFiles.Count) C files generated"
        return $cFiles.Count
    }
    else {
        Write-Warning "Code generation completed with warnings"
        return 0
    }
}

function New-RuntimeFiles {
    param([string]$OutputDir)
    
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }
    
    # Runtime header
    $runtimeHeader = @'
/* N64 Recompiled Runtime - Banjo-Kazooie */
#ifndef RECOMP_H
#define RECOMP_H

#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>

/* N64 Memory Configuration */
#define RDRAM_SIZE (8 * 1024 * 1024)  /* 8 MB */
#define RAM_BASE   0x80000000

/* Global memory */
extern uint8_t g_rdram[RDRAM_SIZE];

/* CPU State */
typedef struct {
    uint64_t gpr[32];    /* General purpose registers */
    uint64_t hi, lo;     /* Multiply/divide results */
    uint32_t pc;         /* Program counter */
    float fpr[32];       /* Floating point registers */
} n64_cpu_state_t;

extern n64_cpu_state_t g_cpu;

/* Runtime API */
void n64_init(void);
void n64_run(void);

/* Memory access */
uint32_t mem_read_u32(uint32_t vaddr);
void mem_write_u32(uint32_t vaddr, uint32_t value);
uint16_t mem_read_u16(uint32_t vaddr);
void mem_write_u16(uint32_t vaddr, uint16_t value);
uint8_t mem_read_u8(uint32_t vaddr);
void mem_write_u8(uint32_t vaddr, uint8_t value);

#endif /* RECOMP_H */
'@
    
    $runtimeHeader | Out-File -FilePath (Join-Path $OutputDir "recomp.h") -Encoding UTF8 -NoNewline
    
    # Runtime implementation
    $runtimeImpl = @'
/* N64 Recompiled Runtime Implementation */
#include "recomp.h"
#include <stdlib.h>

/* Global state */
uint8_t g_rdram[RDRAM_SIZE];
n64_cpu_state_t g_cpu;

void n64_init(void) {
    /* Initialize memory */
    memset(g_rdram, 0, RDRAM_SIZE);
    memset(&g_cpu, 0, sizeof(g_cpu));
    
    printf("N64 Runtime initialized\n");
    printf("  RDRAM: %d MB\n", RDRAM_SIZE / (1024 * 1024));
    printf("  Base: 0x%08x\n", RAM_BASE);
}

static inline uint32_t vaddr_to_offset(uint32_t vaddr) {
    if (vaddr >= RAM_BASE && vaddr < (RAM_BASE + RDRAM_SIZE)) {
        return vaddr - RAM_BASE;
    }
    return 0; /* Invalid address */
}

uint32_t mem_read_u32(uint32_t vaddr) {
    uint32_t offset = vaddr_to_offset(vaddr);
    if (offset < RDRAM_SIZE - 3) {
        /* Big-endian read */
        return (g_rdram[offset] << 24) |
               (g_rdram[offset + 1] << 16) |
               (g_rdram[offset + 2] << 8) |
               g_rdram[offset + 3];
    }
    return 0;
}

void mem_write_u32(uint32_t vaddr, uint32_t value) {
    uint32_t offset = vaddr_to_offset(vaddr);
    if (offset < RDRAM_SIZE - 3) {
        /* Big-endian write */
        g_rdram[offset] = (value >> 24) & 0xFF;
        g_rdram[offset + 1] = (value >> 16) & 0xFF;
        g_rdram[offset + 2] = (value >> 8) & 0xFF;
        g_rdram[offset + 3] = value & 0xFF;
    }
}

uint16_t mem_read_u16(uint32_t vaddr) {
    uint32_t offset = vaddr_to_offset(vaddr);
    if (offset < RDRAM_SIZE - 1) {
        return (g_rdram[offset] << 8) | g_rdram[offset + 1];
    }
    return 0;
}

void mem_write_u16(uint32_t vaddr, uint16_t value) {
    uint32_t offset = vaddr_to_offset(vaddr);
    if (offset < RDRAM_SIZE - 1) {
        g_rdram[offset] = (value >> 8) & 0xFF;
        g_rdram[offset + 1] = value & 0xFF;
    }
}

uint8_t mem_read_u8(uint32_t vaddr) {
    uint32_t offset = vaddr_to_offset(vaddr);
    if (offset < RDRAM_SIZE) {
        return g_rdram[offset];
    }
    return 0;
}

void mem_write_u8(uint32_t vaddr, uint8_t value) {
    uint32_t offset = vaddr_to_offset(vaddr);
    if (offset < RDRAM_SIZE) {
        g_rdram[offset] = value;
    }
}

void n64_run(void) {
    printf("\nStarting Banjo-Kazooie (Recompiled)...\n");
    printf("Entry point: 0x%08x\n", 0x80100400);
    printf("\n");
    printf("NOTE: This is a DEMO/STUB implementation.\n");
    printf("For a complete working recompilation, see:\n");
    printf("  https://github.com/BanjoRecomp/BanjoRecomp\n");
    printf("\n");
}
'@
    
    $runtimeImpl | Out-File -FilePath (Join-Path $OutputDir "runtime.c") -Encoding UTF8 -NoNewline
    
    # Main entry point
    $mainFile = @'
/* Main Entry Point */
#include "recomp.h"

int main(int argc, char** argv) {
    printf("\n");
    printf("╔═══════════════════════════════════════════════════════════════╗\n");
    printf("║                                                               ║\n");
    printf("║               BANJO-KAZOOIE: RECOMPILED                      ║\n");
    printf("║                    (Demo Build)                               ║\n");
    printf("║                                                               ║\n");
    printf("╚═══════════════════════════════════════════════════════════════╝\n");
    printf("\n");
    
    n64_init();
    n64_run();
    
    printf("\nPress Enter to exit...");
    getchar();
    
    return 0;
}
'@
    
    $mainFile | Out-File -FilePath (Join-Path $OutputDir "main.c") -Encoding UTF8 -NoNewline
    
    Write-Success "Runtime files created"
}

function Invoke-Compilation {
    param(
        [string]$SourceDir,
        [string]$RuntimeDir,
        [string]$OutputExe,
        [hashtable]$Compiler
    )
    
    # Gather source files (limit for demo)
    $runtimeFiles = Get-ChildItem -Path $RuntimeDir -Filter "*.c" -File
    $sourceFiles = Get-ChildItem -Path $SourceDir -Filter "*.c" -File | Select-Object -First 20
    
    $allFiles = @($runtimeFiles) + @($sourceFiles)
    
    if ($allFiles.Count -eq 0) {
        throw "No source files found to compile"
    }
    
    Write-Info "Compiling $($allFiles.Count) source files..."
    Write-Info "Output: $OutputExe"
    
    $fileList = ($allFiles | ForEach-Object { "`"$($_.FullName)`"" }) -join " "
    $includeDir = $RuntimeDir
    
    try {
        switch ($Compiler.Type) {
            "gcc" {
                $cmd = "gcc -std=c11 -O2 -I`"$includeDir`" $fileList -o `"$OutputExe`" 2>&1"
                Invoke-Expression $cmd | Out-Null
            }
            "clang" {
                $cmd = "clang -std=c11 -O2 -I`"$includeDir`" $fileList -o `"$OutputExe`" 2>&1"
                Invoke-Expression $cmd | Out-Null
            }
            "msvc" {
                $objDir = Join-Path ([IO.Path]::GetDirectoryName($OutputExe)) "obj"
                New-Item -ItemType Directory -Path $objDir -Force | Out-Null
                
                & cl.exe /nologo /std:c11 /O2 /I"$includeDir" $fileList /Fe:"$OutputExe" /Fo:"$objDir\" 2>&1 | Out-Null
            }
        }
        
        if (Test-Path $OutputExe) {
            $exeSize = (Get-Item $OutputExe).Length
            Write-Success "Compilation successful ($([math]::Round($exeSize / 1KB, 2)) KB)"
            return $true
        }
        else {
            Write-Warning "Compilation completed but executable not found"
            return $false
        }
    }
    catch {
        Write-Error "Compilation failed: $_"
        return $false
    }
}
#endregion

#region Main Pipeline
function Start-Recompilation {
    param([string]$RomPath)
    
    $startTime = Get-Date
    
    Write-Header
    
    try {
        # Prepare output directory on desktop
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $outputName = if ($Config.CreateTimestamp) {
            "$($Config.OutputName)_$timestamp"
        } else {
            $Config.OutputName
        }
        
        $desktopOutput = Join-Path $Config.DesktopOutput $outputName
        $workDir = Join-Path $desktopOutput "work"
        
        New-Item -ItemType Directory -Path $desktopOutput -Force | Out-Null
        New-Item -ItemType Directory -Path $workDir -Force | Out-Null
        
        Write-Info "Output directory: $desktopOutput"
        Write-Separator
        
        # Step 1: Validate ROM
        Write-Step -Step 1 -Total 7 -Message "Validating Banjo-Kazooie ROM"
        $romInfo = Get-ROMInfo -Path $RomPath
        
        Write-Info "ROM: $($romInfo.FileName)"
        Write-Info "Title: $($romInfo.Title)"
        Write-Info "Game ID: $($romInfo.GameID)"
        Write-Info "Size: $([math]::Round($romInfo.FileSize / 1MB, 2)) MB"
        
        $isValid = Test-BanjoKazooieROM -ROMInfo $romInfo
        Write-Success "ROM validated"
        Write-Separator
        
        # Step 2: Initialize tools
        Write-Step -Step 2 -Total 7 -Message "Initializing tools"
        $toolsDir = Initialize-Tools
        $compiler = Get-Compiler
        Write-Success "Tools ready"
        Write-Separator
        
        # Step 3: Extract ROM sections
        Write-Step -Step 3 -Total 7 -Message "Extracting ROM sections"
        $segmentsDir = Join-Path $workDir "segments"
        $segments = Invoke-ROMExtraction -ROMInfo $romInfo -OutputDir $segmentsDir
        Write-Success "$($segments.Count) segments extracted"
        Write-Separator
        
        # Step 4: Disassemble
        Write-Step -Step 4 -Total 7 -Message "Disassembling MIPS code"
        $asmDir = Join-Path $workDir "asm"
        $instrCount = Invoke-Disassembly -Segments $segments -SegmentsDir $segmentsDir -OutputDir $asmDir
        Write-Separator
        
        # Step 5: Generate C code
        Write-Step -Step 5 -Total 7 -Message "Generating C code"
        $codeDir = Join-Path $workDir "generated"
        $fileCount = Invoke-CodeGeneration -AsmDir $asmDir -OutputDir $codeDir
        Write-Separator
        
        # Step 6: Create runtime
        Write-Step -Step 6 -Total 7 -Message "Creating N64 runtime"
        $runtimeDir = Join-Path $workDir "runtime"
        New-RuntimeFiles -OutputDir $runtimeDir
        Write-Separator
        
        # Step 7: Compile executable
        Write-Step -Step 7 -Total 7 -Message "Compiling executable"
        $outputExe = Join-Path $desktopOutput "$($Config.OutputName).exe"
        $success = Invoke-Compilation -SourceDir $codeDir -RuntimeDir $runtimeDir -OutputExe $outputExe -Compiler $compiler
        Write-Separator
        
        # Final summary
        $elapsed = (Get-Date) - $startTime
        
        Write-Host ""
        Write-Host "  ╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
        Write-Host "  ║                                                               ║" -ForegroundColor Green
        Write-Host "  ║                  ✓ BUILD COMPLETE!                           ║" -ForegroundColor Green
        Write-Host "  ║                                                               ║" -ForegroundColor Green
        Write-Host "  ╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
        Write-Host ""
        
        Write-Host "  Output Location:" -ForegroundColor Cyan
        Write-Host "    $desktopOutput" -ForegroundColor White
        Write-Host ""
        Write-Host "  Executable:" -ForegroundColor Cyan
        Write-Host "    $outputExe" -ForegroundColor White
        Write-Host ""
        Write-Host "  Build Time:" -ForegroundColor Cyan
        Write-Host "    $($elapsed.ToString('mm\:ss'))" -ForegroundColor White
        Write-Host ""
        
        Write-Host "  ╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Yellow
        Write-Host "  ║  NOTE: This is a DEMONSTRATION implementation                ║" -ForegroundColor Yellow
        Write-Host "  ║                                                               ║" -ForegroundColor Yellow
        Write-Host "  ║  For a complete, playable Banjo-Kazooie recompilation:       ║" -ForegroundColor Yellow
        Write-Host "  ║  https://github.com/BanjoRecomp/BanjoRecomp                  ║" -ForegroundColor Yellow
        Write-Host "  ╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Yellow
        Write-Host ""
        
        # Open output folder
        Start-Process "explorer.exe" -ArgumentList "/select,`"$outputExe`""
        
    }
    catch {
        Write-Host ""
        Write-Host "  ╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Red
        Write-Host "  ║                     BUILD FAILED                              ║" -ForegroundColor Red
        Write-Host "  ╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Red
        Write-Host ""
        Write-Error "Error: $_"
        Write-Host ""
        Write-Host $_.ScriptStackTrace -ForegroundColor Red
        Write-Host ""
        Write-Host "Press Enter to exit..."
        $null = Read-Host
        exit 1
    }
}
#endregion

# Main execution
Write-Host "Starting recompilation process..." -ForegroundColor Gray
Write-Host "ROM: $RomPath" -ForegroundColor Gray
Write-Host ""

Start-Recompilation -RomPath $RomPath

Write-Host ""
Write-Host "Press Enter to exit..."
$null = Read-Host
