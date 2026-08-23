Universal N64 Recompiler — Drag & Drop Edition (WIP Concept Release)

A cross‑game, cross‑engine recompiler framework for Nintendo 64 titles.
Designed for engineers, modders, and toolchain developers building modernized executables from classic N64 ROMs.

This WIP release demonstrates the architecture, workflow, and runtime model used across all supported titles. It is not a full decompiler; it is a foundation for future expansion.
Purpose of This WIP Release

This concept project shows how a universal N64 recompilation pipeline can be packaged into a simple drag‑and‑drop Windows executable while maintaining a modular backend capable of supporting multiple games, engines, and ROM formats.

The goal is to provide a clean, predictable, automated workflow that engineers can extend into full recompiler implementations.
Quick Start
Requirements

    Windows 10 or Windows 11

    Python 3.8+

    A C/C++ compiler (GCC, MSVC, or Clang)

    A legally‑owned N64 ROM (any supported title)

Setup

    Extract the project to a permanent directory

    Run compile.bat to build the drag‑and‑drop executable

    Install Python dependencies:
    python -m pip install capstone

Usage

    Drag any supported N64 ROM onto the executable

    The tool validates, extracts, disassembles, and recompiles

    Output appears on the Desktop in a timestamped folder

    Run the generated executable from the output directory

Project Structure
Code

N64Recompiler/
├── Recompiler.exe          # Drag-and-drop wrapper
├── Recompiler.cpp          # Wrapper source
├── Recompiler.ps1          # Main pipeline script
├── compile.bat             # Build helper
└── [Desktop Output]/       # Generated per-run
    ├── GameName-Recompiled.exe
    └── work/
        ├── segments/       # Extracted ROM sections
        ├── asm/            # MIPS disassembly
        ├── generated/      # Generated C code (WIP)
        └── runtime/        # N64 runtime implementation

How the Universal Pipeline Works

The recompiler uses a consistent multi‑stage workflow that applies to any supported N64 title.
1. ROM Validation

    Identifies ROM format

    Reads header metadata

    Confirms game ID, entry point, and checksum

    Warns on mismatches but continues for research purposes

2. Tool Initialization

    Verifies Python environment

    Verifies compiler availability

    Loads disassembly and code‑generation modules

3. ROM Extraction

    Normalizes byte‑order

    Splits ROM into boot, code, data, and asset segments

    Generates a reproducible segment map

4. MIPS Disassembly

    Converts machine code to readable assembly

    Uses Capstone for instruction decoding

    Outputs structured .asm files

5. Code Generation (WIP)

    Produces C stubs for functions

    Maps basic control flow

    Prepares structures for future full translation

6. Runtime Creation

    Builds a minimal N64 runtime environment

    Memory model

    CPU state

    Basic system calls

    Placeholder RSP/RDP hooks

7. Compilation

    Compiles generated C code + runtime

    Produces a standalone Windows executable

    Places output on Desktop

Technology Stack

    PowerShell — workflow orchestration

    Python — disassembly, parsing, code generation

    Capstone — MIPS decoding

    C/C++ — final executable build

    Windows APIs — drag‑and‑drop wrapper

Configuration (Universal Model)

Each game is defined by a simple configuration block inside the PowerShell script:
Code

GameID = "XXXX"
GameTitle = "Example Game"
EntryPoint = 0xXXXXXXXX
ExpectedSHA1 = "optional"

Segment extraction is defined per‑game:
Code

$segments = @(
    @{ Name = "boot"; Start = 0x40; End = 0x1000 },
    @{ Name = "code"; Start = 0x1000; End = 0x... },
    @{ Name = "data"; Start = 0x...; End = 0x... }
)

This structure allows engineers to add new games with minimal changes.
Developer Notes
Adapting for New Games

To support another N64 title:

    Update ROM metadata

    Define segment boundaries

    Adjust entry point

    Add game‑specific extraction rules if needed

    Recompile wrapper

Building from Source

Supports MSVC, GCC, and Clang.
Testing

Run the PowerShell script directly for verbose output.
Current WIP Features

    Drag‑and‑drop UX

    ROM validation

    Segment extraction

    MIPS disassembly

    C stub generation

    Minimal runtime

    Windows executable output

    Clean folder structure

    Modular architecture for future expansion

Not Included Yet

This WIP does not include:

    Full MIPS→C translation

    Function signature inference

    Register allocation

    RSP/RDP emulation

    Graphics/audio pipelines

    Asset extraction and loading

    Game‑specific runtime behavior

    Full rebuild capability

These are future milestones.
Path Toward Full Implementation

To evolve this into a complete recompiler:

    Integrate a full instruction translator (Rabbitizer recommended)

    Implement register tracking and calling conventions

    Build a complete N64 runtime (memory, RSP, RDP, input, audio)

    Add asset extraction and loading

    Implement game‑specific behavior modules

    Follow patterns established by N64Recomp and BanjoRecomp

    Expand segment mapping and symbol resolution

References

    N64Recomp

    BanjoRecomp

    Banjo‑Kazooie Decomp

    Capstone Engine
