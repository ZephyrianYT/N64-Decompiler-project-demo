"""Unit tests for the ROM loader, the instruction decoder and the analyzer."""

import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from n64lab import build as builder, homebrew  # noqa: E402
from n64lab.mips import decode  # noqa: E402
from n64lab.rom import Rom, RomError, compute_checksum, to_big_endian  # noqa: E402

PROGRAMS = os.path.join(ROOT, "tests", "programs")


def assemble(*words):
    """A minimal ROM whose boot segment holds the given instruction words."""
    code = b"".join(struct.pack(">I", w) for w in words)
    return Rom.from_bytes(homebrew.make_rom(code))


class RomTests(unittest.TestCase):
    def setUp(self):
        self.z64 = homebrew.make_rom(b"\x03\xe0\x00\x08\x00\x00\x00\x00", title="BYTE ORDER")

    def test_header_fields(self):
        rom = Rom.from_bytes(self.z64)
        self.assertEqual(rom.title, "BYTE ORDER")
        self.assertEqual(rom.entry, 0x80000400)
        self.assertEqual(rom.game_code, "NLBE")
        self.assertTrue(rom.checksum_ok())

    def test_byte_orders_convert_to_big_endian(self):
        v64 = bytearray(self.z64)
        v64[0::2], v64[1::2] = self.z64[1::2], self.z64[0::2]
        n64 = bytearray(self.z64)
        for i in range(4):
            n64[i::4] = self.z64[3 - i::4]
        self.assertEqual(to_big_endian(bytes(v64)), self.z64)
        self.assertEqual(to_big_endian(bytes(n64)), self.z64)
        self.assertEqual(Rom.from_bytes(bytes(n64)).source_format, "n64")

    def test_checksum_detects_changes(self):
        broken = bytearray(self.z64)
        broken[0x2000] ^= 0xFF
        self.assertFalse(Rom.from_bytes(bytes(broken)).checksum_ok())
        self.assertNotEqual(compute_checksum(bytes(broken), "6102"), compute_checksum(self.z64, "6102"))

    def test_rejects_non_roms(self):
        with self.assertRaises(RomError):
            Rom.from_bytes(b"\x00" * 0x2000)


class DecoderTests(unittest.TestCase):
    CASES = [
        (0x27BDFFE8, "addiu   $sp, $sp, -0x18"),
        (0xAFBF0014, "sw      $ra, 0x14($sp)"),
        (0x3C048000, "lui     $a0, 0x8000"),
        (0x03E00008, "jr      $ra"),
        (0x00000000, "nop"),
        (0x00A01025, "move    $v0, $a1"),
        (0x0C000100, "jal     0x80000400"),
        (0x1000FFFF, "b       0x80000400"),
        (0x14400003, "bnez    $v0, 0x80000410"),
        (0x46062100, "add.s   $f4, $f4, $f6"),
        (0x46200021, "cvt.d.d $f0, $f0"),
        (0x4600103C, "c.lt.s  $f2, $f0"),
        (0x0005283C, "dsll32  $a1, $a1, 0"),
        (0xDFBF0010, "ld      $ra, 0x10($sp)"),
        (0x40806000, "mtc0    $zero, $Status"),
    ]

    def test_known_encodings(self):
        for word, text in self.CASES:
            insn = decode(word, 0x80000400)
            if text.startswith("cvt.d.d"):
                self.assertFalse(insn.is_valid)  # converting a double to a double is not an instruction
                continue
            self.assertEqual(insn.text(), text, "0x%08X" % word)

    def test_delay_slot_properties(self):
        self.assertTrue(decode(0x03E00008, 0).has_delay_slot)        # jr $ra
        self.assertTrue(decode(0x50400002, 0).is_likely)             # beql
        self.assertFalse(decode(0x27BDFFE8, 0).has_delay_slot)
        self.assertEqual(decode(0x0C000100, 0x80001000).target, 0x80000400)

    @unittest.skipUnless(shutil.which("llvm-objdump") and shutil.which("clang"), "needs LLVM")
    def test_matches_llvm_objdump(self):
        """Every instruction in the test programs must decode to the same mnemonic as LLVM's."""
        aliases = {"move": {"or", "addu", "daddu"}, "nop": {"sll"}, "b": {"beq"}, "beqz": {"beq"},
                   "bnez": {"bne"}, "beqzl": {"beql"}, "bnezl": {"bnel"}, "negu": {"subu"}, "neg": {"sub"}, "not": {"nor"}, "bal": {"bgezal"},
                   "dnegu": {"dsubu"}, "<unknown>": {"invalid"}}
        with tempfile.TemporaryDirectory() as tmp:
            checked = 0
            for sources in (["float.c"], ["control.c"], ["mips3_main.c", "mips3.S"]):
                elf = os.path.join(tmp, "p.elf")
                homebrew.build([os.path.join(PROGRAMS, s) for s in sources], os.path.join(tmp, "p.z64"),
                               elf_out=elf)
                dump = subprocess.run(["llvm-objdump", "-d", "--mcpu=mips3", "--no-show-raw-insn", elf],
                                      capture_output=True, text=True, check=True).stdout
                raw = subprocess.run(["llvm-objdump", "-d", "--mcpu=mips3", elf],
                                     capture_output=True, text=True, check=True).stdout
                words = {}
                for line in raw.splitlines():
                    m = re.match(r"\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} ){4})", line)
                    if m:
                        words[int(m.group(1), 16)] = int(m.group(2).replace(" ", ""), 16)
                for line in dump.splitlines():
                    m = re.match(r"\s*([0-9a-f]+):\s+(\S+)", line)
                    if not m or int(m.group(1), 16) not in words:
                        continue
                    addr = int(m.group(1), 16)
                    theirs = m.group(2)
                    mine = decode(words[addr], addr)
                    expected = aliases.get(theirs, {theirs})
                    self.assertIn(mine.name, expected | {theirs},
                                  "0x%08X: %08X llvm=%s n64lab=%s" % (addr, words[addr], theirs, mine.name))
                    checked += 1
            self.assertGreater(checked, 1000)


class AnalysisTests(unittest.TestCase):
    def test_function_ends_at_return_unless_a_branch_goes_further(self):
        rom = assemble(
            0x10800002,  # 80000400: beqz $a0, 0x8000040C
            0x00000000,  #           nop
            0x03E00008,  # 80000408: jr $ra      <- not the end: the branch targets 0x8000040C
            0x24020001,  #           addiu $v0, $zero, 1   (delay slot... of jr at 408)
            0x03E00008,  # 80000410: jr $ra
            0x24020002,  #           addiu $v0, $zero, 2
        )
        program = builder.make_program(rom)
        func = program.functions[0x80000400]
        self.assertEqual(func.end, 0x80000418)

    def test_jal_targets_become_functions(self):
        rom = assemble(
            0x0C000104,  # 80000400: jal 0x80000410
            0x00000000,
            0x1000FFFF,  # 80000408: b 0x80000408 (loop forever)
            0x00000000,
            0x03E00008,  # 80000410: jr $ra
            0x00000000,
        )
        program = builder.make_program(rom)
        self.assertEqual(sorted(program.functions), [0x80000400, 0x80000410])
        self.assertIn("called by", program.functions[0x80000410].reason)

    def test_code_pointer_is_discovered(self):
        rom = assemble(
            0x3C028000,  # 80000400: lui   $v0, 0x8000
            0x24420418,  #           addiu $v0, $v0, 0x418   (pointer to a function)
            0x0040F809,  #           jalr  $v0
            0x00000000,
            0x1000FFFF,  # 80000410: b .
            0x00000000,
            0x03E00008,  # 80000418: jr $ra
            0x00000000,
        )
        program = builder.make_program(rom)
        self.assertIn(0x80000418, program.functions)


if __name__ == "__main__":
    unittest.main()


class FuzzTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("clang"), "needs clang")
    def test_random_code_always_produces_valid_c(self):
        """Data mistaken for code, odd branches, etc. must never break the generated C."""
        import random
        for seed in range(4):
            r = random.Random(seed)
            words = []
            for _ in range(2000):
                k = r.random()
                if k < 0.3:
                    words.append(r.getrandbits(32))
                elif k < 0.5:   # branches with short offsets
                    words.append((r.choice([4, 5, 20, 21]) << 26) | (r.getrandbits(10) << 16) | (r.randint(-30, 30) & 0xFFFF))
                elif k < 0.6:   # jal/j inside the code
                    words.append((r.choice([2, 3]) << 26) | ((0x80000400 + 4 * r.randint(0, 1999)) >> 2 & 0x3FFFFFF))
                elif k < 0.7:
                    words.append(0x03E00008)
                else:
                    words.append((r.randint(8, 63) << 26) | r.getrandbits(26))
            program = builder.make_program(assemble(*words))
            with tempfile.TemporaryDirectory() as out:
                builder.write_project(program, out, "fuzz")
                sources = [os.path.join("src", f) for f in os.listdir(os.path.join(out, "src")) if f.endswith(".c")]
                result = subprocess.run(["clang", "-std=c11", "-fsyntax-only", "-Iruntime", "-Isrc"] + sources,
                                        cwd=out, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr[:2000])
