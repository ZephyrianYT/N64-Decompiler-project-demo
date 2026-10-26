"""Build tiny N64 ROMs from C with clang + lld, for experimenting and testing.

    python -m n64lab homebrew examples/hello/hello.c -o hello.z64

The program is compiled for MIPS II, the instruction set most N64 games were
built with, linked to run from 0x80000400 and wrapped in a ROM header.  The
ROM has an empty IPL3 boot block, which is enough for n64lab but not for a
real console or most emulators (those need a real IPL3, e.g. libdragon's).
"""

import os
import shutil
import struct
import subprocess
import tempfile

from .rom import GAME_START, CHECKSUM_LENGTH, compute_checksum

HOMEBREW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "homebrew")
ENTRY = 0x80000400

CFLAGS = [
    "--target=mips-none-elf", "-march=mips2", "-mabi=32", "-mfp32",
    "-mno-abicalls", "-fno-pic", "-G0",          # plain absolute addressing, like N64 games
    "-ffreestanding", "-fno-builtin", "-nostdlib", "-fomit-frame-pointer",
    "-fno-math-errno",                           # lets sqrtf() become the sqrt.s instruction
    "-Wall",
]


class ToolchainError(RuntimeError):
    pass


def _tool(*names):
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    raise ToolchainError("%s not found; install LLVM (clang + lld) to build homebrew ROMs" % names[0])


def find_toolchain():
    suffixes = ["", "-18", "-17", "-16", "-15", "-19", "-20"]
    return {
        "clang": _tool(*["clang" + s for s in suffixes]),
        "ld": _tool(*["ld.lld" + s for s in suffixes]),
        "objcopy": _tool(*["llvm-objcopy" + s for s in suffixes]),
        "nm": _tool(*["llvm-nm" + s for s in suffixes]),
    }


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ToolchainError("command failed: %s\n%s%s" % (" ".join(cmd), result.stdout, result.stderr))


def make_rom(binary, title="N64LAB TEST", game_code="NLBE"):
    """Wrap a flat binary (loaded at 0x80000400) in an N64 ROM image."""
    if len(binary) > 0x100000:
        raise ValueError("program is larger than the 1 MiB that IPL3 loads")
    header = bytearray(GAME_START)
    struct.pack_into(">IIII", header, 0, 0x80371240, 0x0000000F, ENTRY, 0x0000144C)
    header[0x20:0x34] = title.encode("ascii")[:20].ljust(20, b" ")
    header[0x3B:0x3F] = game_code.encode("ascii")[:4]
    rom = bytearray(header) + bytearray(binary)
    rom += bytes(GAME_START + CHECKSUM_LENGTH - len(rom))  # checksum covers 1 MiB
    crc1, crc2 = compute_checksum(bytes(rom), "6102")
    struct.pack_into(">II", rom, 0x10, crc1, crc2)
    return bytes(rom)


def build(sources, out_rom, title="N64LAB TEST", opt="-O2", symbols_out=None, extra_cflags=(),
          elf_out=None):
    tools = find_toolchain()
    with tempfile.TemporaryDirectory(prefix="n64lab_") as tmp:
        inputs = [os.path.join(HOMEBREW_DIR, "crt0.S"), os.path.join(HOMEBREW_DIR, "n64lab.c")]
        inputs += list(sources)
        objects = []
        for n, src in enumerate(inputs):
            obj = os.path.join(tmp, "%02d_%s.o" % (n, os.path.basename(src)))
            flags = CFLAGS + [opt, "-I", HOMEBREW_DIR] + list(extra_cflags)
            if src.endswith((".S", ".s")):
                flags = [f for f in flags if not f.startswith("-march")] + ["-march=mips3"]
            _run([tools["clang"]] + flags + ["-c", src, "-o", obj])
            objects.append(obj)
        elf = os.path.join(tmp, "program.elf")
        binary = os.path.join(tmp, "program.bin")
        _run([tools["ld"], "-T", os.path.join(HOMEBREW_DIR, "link.ld"), "-o", elf] + objects)
        _run([tools["objcopy"], "-O", "binary", elf, binary])
        with open(binary, "rb") as f:
            rom = make_rom(f.read(), title)
        if symbols_out:
            write_symbols(tools["nm"], elf, symbols_out)
        if elf_out:
            shutil.copy(elf, elf_out)
    with open(out_rom, "wb") as f:
        f.write(rom)
    return out_rom


def write_symbols(nm, elf, out_path):
    """Save function names as `name = 0xADDR;` so the recompiler output uses them."""
    result = subprocess.run([nm, elf], capture_output=True, text=True, check=True)
    lines = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in ("T", "t") and not parts[2].startswith("$"):
            lines.append("%s = 0x%s;" % (parts[2], parts[0].upper()))
    with open(out_path, "w") as f:
        f.write("\n".join(sorted(set(lines))) + "\n")
