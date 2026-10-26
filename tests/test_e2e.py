"""End-to-end tests: C program -> N64 ROM -> recompiled C -> executable.

Each program in tests/programs is built twice:
  1. natively for this PC (the expected output), and
  2. for the N64 with clang, then recompiled by n64lab and run.
Both runs must print exactly the same text.

Needs clang + ld.lld (to build N64 code) and a host C compiler.  Set
N64LAB_TEST_WINDOWS=1 to also cross-build with MinGW and run under Wine.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from n64lab import build as builder, homebrew  # noqa: E402
from n64lab.analysis import load_symbols  # noqa: E402
from n64lab.interp import run_rom  # noqa: E402
from n64lab.rom import Rom  # noqa: E402

PROGRAMS = os.path.join(ROOT, "tests", "programs")
EXPECTED = os.path.join(PROGRAMS, "expected")


def have_toolchain():
    try:
        homebrew.find_toolchain()
    except homebrew.ToolchainError:
        return False
    return builder.find_compiler("native") is not None


def wine():
    for path in ("wine64", "/usr/lib/wine/wine64", "wine"):
        if shutil.which(path):
            return shutil.which(path)
    return None


@unittest.skipUnless(have_toolchain(), "needs clang, ld.lld and a C compiler")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="n64lab_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def recompile(self, name, sources, target="native", opt="-O2"):
        work = os.path.join(self.tmp, "%s_%s_%s" % (name, target, opt.strip("-")))
        os.makedirs(work, exist_ok=True)
        rom_path = os.path.join(work, name + ".z64")
        sym_path = os.path.join(work, name + ".sym")
        homebrew.build(sources, rom_path, opt=opt, symbols_out=sym_path)
        rom = Rom.load(rom_path)
        self.assertTrue(rom.checksum_ok())
        # Analyze without the symbol file first: discovery must work on its own.
        program = builder.make_program(rom)
        reached = set(program.functions)
        for f in program.functions.values():
            for warning in f.warnings:
                self.fail("%s: %s: %s" % (name, f.name, warning))
        symbols = load_symbols(sym_path)
        program = builder.make_program(rom, {"_symbols_file": sym_path})
        self.assertIn(rom.entry, program.functions)
        out = os.path.join(work, "recomp")
        exe_name = builder.write_project(program, out, name)
        exe = builder.compile_project(out, exe_name, target=target, log=lambda *_: None)
        return rom_path, exe, symbols, reached

    def run_exe(self, exe, rom_path, use_wine=False):
        cmd = [exe, rom_path, "--headless", "--seconds", "60"]
        if use_wine:
            cmd = [wine()] + cmd
        env = dict(os.environ, WINEDEBUG="-all")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
        self.assertIn("program finished", result.stderr, result.stderr)
        return result.stdout

    def native_output(self, name, source):
        exe = os.path.join(self.tmp, name + "_native")
        cc = builder.find_compiler("native")
        subprocess.run([cc, "-O1", "-I", homebrew.HOMEBREW_DIR, source, "-o", exe, "-lm"], check=True)
        return subprocess.run([exe], capture_output=True, text=True, check=True).stdout

    def check_program(self, name, opt="-O2"):
        source = os.path.join(PROGRAMS, name + ".c")
        expected = self.native_output(name, source)
        rom_path, exe, _, _ = self.recompile(name, [source], opt=opt)
        self.assertEqual(self.run_exe(exe, rom_path), expected)
        # The interpreter is a separate implementation of the CPU; it must agree too.
        output, reason = run_rom(Rom.load(rom_path))
        self.assertIn("BREAK", reason)
        self.assertEqual(output, expected)

    def test_arith(self):
        self.check_program("arith")

    def test_arith_unoptimized(self):
        self.check_program("arith", opt="-O0")

    def test_control(self):
        self.check_program("control")

    def test_control_size_optimized(self):
        self.check_program("control", opt="-Os")

    def test_memory(self):
        self.check_program("memory")

    def test_float(self):
        self.check_program("float")

    def test_float_unoptimized(self):
        self.check_program("float", opt="-O0")

    def test_mips3_assembly(self):
        """Hand-written MIPS III: 64-bit ops, likely branches, odd delay slots."""
        sources = [os.path.join(PROGRAMS, "mips3_main.c"), os.path.join(PROGRAMS, "mips3.S")]
        rom_path, exe, _, _ = self.recompile("mips3", sources)
        with open(os.path.join(EXPECTED, "mips3.txt")) as f:
            expected = f.read()
        self.assertEqual(self.run_exe(exe, rom_path), expected)
        self.assertEqual(run_rom(Rom.load(rom_path))[0], expected)

    def test_function_discovery_without_symbols(self):
        """Every function main() can reach must be found from the entry point alone."""
        source = os.path.join(PROGRAMS, "control.c")
        _, _, symbols, reached = self.recompile("discovery", [source])
        by_name = {name: addr for addr, name in symbols.items()}
        for name in ("main", "lab_printf", "lab_puts", "put_number"):
            self.assertIn(by_name[name], reached, name)

    @unittest.skipUnless(os.environ.get("N64LAB_TEST_WINDOWS") and wine() and
                         builder.find_compiler("windows"), "set N64LAB_TEST_WINDOWS=1 (needs MinGW + Wine)")
    def test_windows_build_under_wine(self):
        source = os.path.join(PROGRAMS, "control.c")
        expected = self.native_output("control_win", source)
        rom_path, exe, _, _ = self.recompile("control", [source], target="windows")
        self.assertEqual(self.run_exe(exe, rom_path, use_wine=True).replace("\r\n", "\n"), expected)


if __name__ == "__main__":
    unittest.main()
