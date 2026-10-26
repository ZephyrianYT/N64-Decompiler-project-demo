# n64lab: an N64 → Windows static recompiler for learning

n64lab takes an N64 ROM, finds the machine code in it, translates every MIPS
instruction into C, and compiles that C, together with a small runtime that
stands in for the console's hardware, into a native Windows program.

It's built to be read. The generated C has one statement per MIPS instruction,
with the original instruction beside it:

```c
void fn_fibonacci(CPUState* cpu) {
    cpu->sp = S32(cpu->sp - 0x10);              // 800016FC: addiu   $sp, $sp, -0x10
    SW(cpu->sp, 0xC, cpu->ra);                  // 80001700: sw      $ra, 0xC($sp)
    ...
    cpu->ra = S32(0x80001730);                  // 80001728: jal     fibonacci  (call)
    cpu->a0 = S32(cpu->s0 - 0x1);               // 8000172C: addiu   $a0, $s0, -0x1  (delay slot)
    fn_fibonacci(cpu);
```

The Python side is about 2,500 lines with no dependencies, and the C runtime is
about 1,200 lines. Every stage can be run and inspected on its own.

> **What this is and isn't.** n64lab fully runs programs that drive the
> hardware directly: text output, a framebuffer, the controller. Commercial
> games recompile and compile, but they won't *play*. They depend on the
> RSP/RDP graphics and audio processors and on libultra's threads and
> interrupts, none of which this runtime emulates. Making a commercial game
> playable is what projects like [N64Recomp](https://github.com/N64Recomp/N64Recomp)
> spend years on. [docs/LEARNING.md](docs/LEARNING.md) explains exactly what's
> missing and why.

## Quick start (Windows)

1. Install [Python 3.8+](https://www.python.org/downloads/) (tick "Add python.exe to PATH").
2. Install a C compiler. The easiest is [winlibs MinGW-w64](https://winlibs.com):
   take a release "with LLVM/Clang/LLD", unzip it, and add its `bin` folder
   to PATH. That gives you gcc and clang for compiling the recompiled C, plus
   the clang and lld needed to build the example ROMs. Visual Studio's `cl`
   (run from a Developer Command Prompt) and MSYS2 work too.
3. Drag a ROM onto **`n64lab.bat`**.

The tool recompiles the ROM into `<rom name>_recomp\`, builds `<title>.exe`,
and runs it. A window shows the framebuffer, and the console shows the log and
anything the program prints.

To try it without a commercial ROM, build one of the example programs:

```bat
python -m n64lab homebrew examples\bounce\bounce.c -o bounce.z64
```

Then drag `bounce.z64` onto `n64lab.bat`. Hold **X** (the A button) and use the
arrow keys to steer the square.

## Commands

Everything is also available from the command line (Windows, Linux or macOS):

```sh
python -m n64lab info      game.z64            # header, boot chip (CIC), checksum
python -m n64lab functions game.z64            # what the analyzer found and why
python -m n64lab disasm    game.z64 [--function 0x80000400]
python -m n64lab trace     game.z64 --steps 50 # interpret, printing every instruction
python -m n64lab recomp    game.z64 [-o out] [--build | --run] [--target windows]
python -m n64lab homebrew  my.c -o my.z64      # build a test ROM from C (needs clang + lld)
```

`recomp --target windows` cross-compiles a `.exe` from Linux or macOS with MinGW.
On Linux and macOS the native build runs headless: it prints output and can
save the framebuffer with `--screenshot frame.ppm`.

Options for the generated program:

```
game.exe [rom.z64] [--headless] [--seconds N] [--screenshot F.ppm] [--trace-mmio] [--scale N]
```

`--trace-mmio` logs every video register write and cartridge DMA, so you can
watch how a program talks to the hardware.

## Docker

The image contains the whole toolchain: Python, clang + lld for building
homebrew ROMs, gcc, and MinGW for cross-compiling Windows `.exe` files. Mount
your working folder at `/work`:

```sh
docker build -t n64lab .
docker run --rm -v "$PWD:/work" -u "$(id -u):$(id -g)" n64lab info game.z64
docker run --rm -v "$PWD:/work" -u "$(id -u):$(id -g)" n64lab recomp game.z64 --build --target windows
docker run --rm -u "$(id -u):$(id -g)" --entrypoint python3 n64lab -m unittest discover -s /opt/n64lab/tests
```

`-u` makes the generated files belong to you rather than root. On Windows
(PowerShell), use `-v "${PWD}:/work"` and leave out `-u`. Containers have no
display, so the recompiled program runs headless there. Copy the `.exe` out
and run it on Windows to see the window. Add `--build-arg WITH_WINE=1` to
`docker build` to include Wine for the Windows end-to-end test.

## Parallel work

- **Recompiling** (`-j N`, default: all cores). The generated C is split into
  files of about 6,000 instructions each, and the files are compiled in
  parallel. On Linux, translating functions to C also runs in worker
  processes for large ROMs. On Windows and macOS that step stays serial:
  Python has to send each worker a copy of the analyzed program, and
  measured, that cost more than it saved. Analysis is serial everywhere,
  because each function discovered can change the boundaries of others.
- **Running.** The recompiled program runs on its own thread, and the
  window or headless monitor runs on another. See "Many things at once" in
  [docs/LEARNING.md](docs/LEARNING.md) for how a real N64's parallel
  hardware maps onto PC threads.

## How it works

```
 ROM ──► rom.py ──► analysis.py ──► codegen.py ──► build.py ──► C compiler ──► .exe
        header,     find functions,  one C line     write project,          + runtime/
        byte order, labels, jump     per MIPS       compile in              (memory map,
        boot code   tables           instruction    parallel                 video, input)
```

| File | Role |
|---|---|
| `n64lab/rom.py` | ROM byte orders (.z64/.v64/.n64), header, CIC detection, the boot checksum |
| `n64lab/mips.py` | Table-driven decoder for the VR4300's MIPS III instruction set |
| `n64lab/analysis.py` | Finds functions from the entry point, branch labels, switch jump tables, function pointers |
| `n64lab/codegen.py` | Turns each function into C, handling delay slots, branch-likely and indirect jumps |
| `n64lab/build.py` | Writes the C project and compiles it |
| `n64lab/interp.py` | A separate MIPS interpreter (`trace`), also used to cross-check the recompiler |
| `n64lab/runtime/` | The C runtime: CPU helpers, the N64 memory map and hardware registers, Win32 window |
| `n64lab/homebrew/` | A tiny SDK and toolchain setup for writing your own test ROMs |

The generated project in `<rom>_recomp/` is self-contained: it has its own
`build.bat`, `Makefile` and `CMakeLists.txt`, and the disassembly it came from
is in `asm/`.

**[docs/LEARNING.md](docs/LEARNING.md)** walks through all of this step by
step, with exercises.

## Tests

```sh
python -m unittest discover -s tests -v
```

The end-to-end tests compile each program in `tests/programs/` twice: natively
for the PC, and for the N64. The N64 build is then both recompiled and
interpreted, and all three must print exactly the same output. The programs
cover integer and 64-bit math, switches, function pointers, structs and
unaligned memory, floating point, plus hand-written MIPS III assembly for the
corner cases compilers rarely emit. Another test checks the decoder against
LLVM's disassembler. Set `N64LAB_TEST_WINDOWS=1` to also cross-build the
Windows `.exe` and run it under Wine.

## Legal

Only use ROMs you dumped from cartridges you own. Recompiled output contains
the game's code, so don't share it. `legacy/` holds this repository's earlier
Banjo-Kazooie concept.
