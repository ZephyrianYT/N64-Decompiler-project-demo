# Learning N64 recompilation with n64lab

This guide takes you from "what's in a ROM file" to "why commercial games are
hard", using n64lab at every step. Each section names the source file that
does the work. They're short and meant to be read alongside this guide.

Build the two examples first, so you have ROMs to poke at:

```sh
python -m n64lab homebrew examples/hello/hello.c -o hello.z64
python -m n64lab homebrew examples/bounce/bounce.c -o bounce.z64
```

---

## 0. Recompile, decompile, emulate: what's the difference?

| Approach | What it does | Example projects |
|---|---|---|
| **Emulation** | Runs the original machine code on a simulated console, one instruction at a time (or JIT-compiled at runtime) | Project64, ares, `n64lab trace` |
| **Static recompilation** | Translates all the machine code to C (or another language) *ahead of time*, then compiles that for the PC | N64Recomp, **n64lab** |
| **Decompilation** | People rewrite the game as readable C that compiles back to the *exact same bytes* | the SM64, OoT and Banjo decomps |

A recompiler's output is correct but mechanical: registers become variables,
and every instruction becomes a statement. A decompilation reads like real
source code, but each function takes a human hours. Recompilation is
automatic. That makes it a good place to learn how the machine works, and it's
how projects like Zelda 64: Recompiled were built.

---

## 1. Anatomy of a ROM (`rom.py`)

```sh
python -m n64lab info hello.z64
```

- **Byte order.** Cartridge dumps exist in three byte orders: `.z64`
  (big-endian, the console's native order), `.v64` (16-bit swapped) and
  `.n64` (32-bit little-endian). The first word is always `0x80371240` in
  native order, so you can tell which one you have. See `detect_format`.
- **Header (0x00–0x3F).** Holds the entry point (0x08), two checksum words
  (0x10), the title (0x20) and the game code (0x3B), e.g. `NSME`: N = cartridge,
  SM = Super Mario 64, E = USA.
- **IPL3 (0x40–0xFFF).** Boot code that runs from the cartridge. It checks the
  checksum, then copies the first **1 MiB** of the game (ROM 0x1000 onward)
  into RAM at the entry point and jumps there. n64lab recompiles that 1 MiB
  by default.
- **CIC.** A lockout chip on every cartridge. Each CIC type has its own IPL3,
  so n64lab identifies the CIC by hashing the IPL3 (`CIC_BY_IPL3_CRC`). This
  matters: CIC-6103 and CIC-6106 load the game 1 or 2 MiB *lower* than the
  header says, so the recompiler would look in the wrong place without it.

Try it: corrupt one byte past 0x1000 in a copy of `hello.z64` with a hex editor
and run `info` again. The checksum turns to MISMATCH. `compute_checksum`
reproduces the algorithm IPL3 uses.

---

## 2. Reading MIPS (`mips.py`)

The N64's CPU is a NEC VR4300: a MIPS III processor with 32 64-bit registers.
Every instruction is exactly 4 bytes.

```sh
python -m n64lab disasm hello.z64 --symbols hello.sym --function 0x800016FC
```

The decoder is a set of lookup tables. The top 6 bits select a row in
`OPCODES`, and three opcodes (SPECIAL, REGIMM, COP1) select from a second
table. Every instruction falls into one of three layouts:

```
R-type: | op | rs | rt | rd | sa | funct |   addu  $v0, $a0, $a1
I-type: | op | rs | rt |   immediate   |   addiu $sp, $sp, -0x18
J-type: | op |        target          |   jal   0x80001234
```

Register conventions you'll see everywhere: `$a0–$a3` hold arguments, `$v0`
holds the return value, `$sp` is the stack pointer, `$ra` is the return address,
and `$s0–$s7` are preserved across calls.

### Delay slots: the key MIPS quirk

The instruction **after** a branch or jump always runs before the jump takes
effect:

```
jr    $ra              # return...
addiu $sp, $sp, 0x18   # ...but this runs first
```

Watch it happen with the interpreter:

```sh
python -m n64lab trace hello.z64 --symbols hello.sym --steps 120
```

Every line shows the instruction and the registers or memory it changed. The
first ~100 steps are the startup code zeroing memory. Then comes `jal main`:
notice that the instruction after it executes before the first instruction of
`main`.

*Branch-likely* instructions (`beql`, `bnel`, ...) are a twist: their delay
slot only runs if the branch is taken. Compilers for the N64 used them a lot.

---

## 3. Finding the code (`analysis.py`)

A ROM has no symbol table. Code, data, graphics and music are all just bytes.
The analyzer has to work out where functions are:

```sh
python -m n64lab functions hello.z64
```

The "found because" column shows how each function was discovered:

1. **Entry point**, from the header.
2. **Called by**: every `jal` target is a function.
3. **Address taken**: `lui`+`addiu` pairs that build an address inside the
   code are probably function pointers (callbacks, thread entry points).
   They're accepted if the bytes there look like code (`_plausible`).
4. **Tail call**: a `j` to another function instead of a `jal`.

A function ends at `jr $ra` **only if** no branch seen so far jumps past
that point. Otherwise the `jr $ra` is an early return in the middle
(`_scan` tracks this as `furthest`).

**Jump tables.** A dense `switch` compiles to an array of code addresses plus
`jr $reg`. `_find_jump_table` walks backwards from the `jr` to find the
`lui`/`addu`/`lw` that loaded the target, which reveals the table's address.
The bounds check (`sltiu`) before it gives the table's size.

Exercise: run `functions` with and without `--symbols hello.sym`. Without
symbols, which functions are missing, and why? (Hint: who calls
`lab_video_init` in hello.c?)

---

## 4. Translating to C (`codegen.py`)

```sh
python -m n64lab recomp hello.z64 --symbols hello.sym
```

Open `hello_recomp/src/funcs_000.c` next to `hello_recomp/asm/*.s`. The CPU
becomes a struct (`n64lab/runtime/n64_runtime.h`):

```c
typedef struct CPUState { uint64_t r[32] /* also named zero, at, v0... */; uint64_t hi, lo;
                          uint32_t f[32]; uint32_t fcr31; ... } CPUState;
```

and each MIPS function becomes `void func_XXXXXXXX(CPUState* cpu)`.

| MIPS | C | Why |
|---|---|---|
| `addu $v0, $a0, $a1` | `cpu->v0 = S32(cpu->a0 + cpu->a1);` | 32-bit ops sign-extend their result into the 64-bit register |
| `lw $t0, 4($sp)` | `cpu->t0 = LW(cpu->sp, 0x4);` | memory goes through the runtime (it's big-endian, and may be hardware) |
| `jal func` | `cpu->ra = ...; <delay slot>; func(cpu);` | the delay slot runs first, then a real C call |
| `jr $ra` | `<delay slot>; return;` | returning is a C return, because calls are C calls |
| `beq` | `<delay slot>; if (...) goto L_...;` | branches inside a function become `goto` |
| `jr $t0` with a jump table | `switch (target) { case 0x...: goto L_...; }` | |
| `jalr $t9` | `n64_call(cpu, target);` | function pointers are looked up in a table at runtime |

The delay slot ordering creates a trap. In

```
bnez  $t0, somewhere
move  $t0, $zero     # delay slot overwrites $t0
```

the branch must test the *old* `$t0`. The generator spots this (comparing what
the delay slot `writes` with what the branch `reads`) and saves the condition
first:

```c
{
    int taken = cpu->t0 != 0;  // test before the delay slot changes it
    cpu->t0 = 0;
    if (taken) goto L_80001E9C;
}
```

The hand-written test `tests/programs/mips3.S` has this case and several other
odd ones. Read it alongside its recompiled output.

---

## 5. Pretending to be an N64 (`runtime/`)

The generated code can't touch hardware directly, so every load and store goes
to `n64_memory.c`, which implements the console's memory map:

| Address | What | n64lab |
|---|---|---|
| `0x80000000` | RDRAM (main memory), cached | 8 MiB array, stored big-endian |
| `0xA0000000` | the same RAM, uncached | same array |
| `0xA4400000` | Video Interface (VI) registers | the window reads them to find the framebuffer |
| `0xA4600000` | Peripheral Interface (PI) | DMA from cartridge to RAM, implemented |
| `0xA4800000` | Serial Interface (SI) → PIF chip | controller 1, mapped to the keyboard |
| `0xB0000000` | cartridge ROM | read-only view of the ROM file |
| `0xB3FF0000` | IS-Viewer debug port | `printf` output |

Try:

```sh
python -m n64lab recomp bounce.z64 --run -- --trace-mmio --seconds 2
```

and watch `lab_video_init` program the VI registers one by one. Then read
`n64_framebuffer()` to see how `VI_ORIGIN`, `VI_WIDTH` and `VI_CTRL` decide
what appears in the window.

**Endianness.** The N64 is big-endian and a PC is little-endian. n64lab keeps
RAM in the N64's byte order and assembles each value byte by byte
(`mem_read32`). DMA is then a plain copy, and the code stays easy to follow.
N64Recomp uses a faster trick: it byte-swaps each 32-bit word and XORs byte
addresses with 3.

**Threads.** The recompiled program runs on its own thread. The window
thread redraws from RAM 60 times a second, just like the TV reading the
framebuffer on a real console, independently of the CPU.

### Many things at once

An N64 is a multiprocessor machine. While the CPU runs game code:

| Unit | Runs | In n64lab |
|---|---|---|
| CPU (VR4300) | game logic, libultra threads | the **game thread** (recompiled code) |
| VI | scans the framebuffer out to the TV, 60 times a second | the **window/monitor thread** |
| RSP | microcode: vertex transforms, audio mixing | not emulated |
| RDP | rasterizes triangles into the framebuffer | not emulated |
| AI, PI, SI | audio playback, cartridge and controller DMA | done instantly, on the game thread |

The two threads n64lab uses share RDRAM without locks. That's deliberate,
and faithful: the real VI also reads memory while the CPU writes it, which
is why games double-buffer and swap `VI_ORIGIN` during vblank. You can see
the tearing yourself by drawing in `bounce.c` without waiting for vblank.

A full runtime has more concurrency to map:

- **libultra threads.** Games create 4 to 10 threads (main, graphics, audio,
  scheduler, idle) that the OS switches between on a single CPU. Instead of
  emulating the switch, ultramodern runs each one as a real host thread,
  with only one allowed to run at a time. That's needed because N64 code
  assumes a single core: it uses priorities instead of locks. Running them
  truly in parallel would break those assumptions.
- **RSP/RDP.** These do run in parallel with the CPU on real hardware, so a
  renderer can safely use its own thread (or the GPU). The game only waits
  for "task done" interrupts.
- **Audio.** Needs its own thread at a steady rate, or it crackles.

---

## 6. Why commercial games don't run (yet)

Recompile a game you own, then look at how far it gets with
`--trace-mmio`. You'll hit these walls, roughly in this order:

1. **The operating system.** Games use libultra, Nintendo's small OS with
   threads, message queues and interrupts. Switching threads works by saving
   registers and executing `eret` from an exception handler. A recompiled
   program can't do that, because "return to a different thread" isn't
   expressible as a C call. N64Recomp's solution, *ultramodern*, replaces
   libultra's functions (`osCreateThread`, `osRecvMesg`, ...) with
   native implementations built on real OS threads. Use n64lab's `stubs`
   config to see how far skipping functions gets you, and read
   "Stubs and hangs" below first.
2. **Interrupts.** Games wait on VI (vblank) and SP/DP (task done) interrupts.
   n64lab never raises them, so `osRecvMesg` waits forever.
3. **The RSP and RDP.** 3D graphics and audio aren't drawn by the CPU. The CPU
   sends *display lists* to microcode running on the RSP, which feeds the RDP
   rasterizer. The runtime logs "RSP task started" and ignores it. Real
   recompilations use a renderer like [RT64](https://github.com/rt64/rt64),
   which interprets display lists with a modern GPU.
4. **Overlays and the TLB.** Many games load code into the same RAM address at
   different times (overlays), or map memory with the TLB (GoldenEye,
   Perfect Dark). Static recompilation needs to know about every piece of
   code and where it runs. Decomp projects describe this with
   [splat](https://github.com/ethteck/splat) configs, and N64Recomp reads
   their symbol files. n64lab's `segments` and `symbols` config options are
   simple versions of the same idea.

Each wall is a good project. The best next step is probably item 1 for a single
thread: stub out `osCreateThread`/`osStartThread` and call the main thread's
entry function directly.

---

### Stubs and hangs

A stub replaces a function with an empty one. That's dangerous for any
function a caller *waits on*:

```c
while (!device_ready()) {}          /* or: osRecvMesg(queue, &msg, OS_MESG_BLOCK) */
```

If `device_ready` is stubbed, it returns whatever `$v0` held, which is often
0, and the loop spins forever. A spin looks just like a slow program. Two
tools help:

- **Find the hang:** recompile with `--debug-calls` and stop the program
  (`--seconds 5` or Ctrl+C). It prints the stack of recompiled functions it
  was in.
- **Give stubs a return value**, so a waiting caller sees success. Config
  entries can use function names from your symbol file:

  ```json
  { "stubs": { "device_ready": 1, "osRecvMesg": 0, "osSetIntMask": null } }
  ```

  `null` (or a plain list of stubs) leaves `$v0` untouched.
  `tests/programs/waits.c` is a small program that hangs exactly like this.
  Try both tools on it.

A stub can only *return*. It can't do the function's side effects, such as
filling in the message `osRecvMesg` was supposed to deliver. That's why real
recompilations replace these functions with working native code instead.

### Limits of one C function per MIPS function

All recompiled functions share the single `CPUState`, so registers flow
through calls and jumps exactly as on the console. Splitting the code into
C functions only decides how *control* moves, and two patterns don't fit:

- **Jumps to a computed address in the middle of a function**, e.g.
  `longjmp`, or libultra resuming a thread at its saved PC via `eret`.
  C can only enter a function at its start, so the runtime stops with
  "no function was recompiled there".
- **Functions that jump (`j`, not `jal`) to each other in a loop.** Each jump
  becomes a C call that never returns, so the native stack grows until it
  overflows. Compilers rarely produce this, but hand-written assembly can.
  `--debug-calls` warns when calls nest 100,000 deep.

Production recompilers handle the first by replacing those OS functions,
and the second by merging such functions or using a dispatch loop.

---

## 7. Exercises

1. Write a C function with a `switch` of 8+ cases into a test program, and
   find the jump table in `functions` output and in the generated C.
2. In `bounce.c`, switch to a 32-bit framebuffer (`lab_video_init(fb, 32)`
   with `unsigned int` pixels). Which VI register changes?
3. Add a missing instruction to the interpreter (hint: it doesn't handle
   `tlbwi`), or a new hardware register to the runtime.
4. Make `--trace-mmio` print *which function* touched each register. (You'll
   need the generated code to record the current function in a global.)
5. Compare `python -m n64lab trace` with the recompiled build for the same
   program. How many times faster is the recompiled version?
6. Read [N64Recomp's README](https://github.com/N64Recomp/N64Recomp) and match
   each concept there to the n64lab file that does the simple version.

## Further reading

- [n64brew wiki](https://n64brew.dev): the best hardware reference (memory map, VI, PI, SI, PIF)
- *MIPS IV Instruction Set* and the *VR4300 User's Manual*: the official CPU docs
- [N64Recomp](https://github.com/N64Recomp/N64Recomp): the production-grade version of this idea
- [decomp.me](https://decomp.me): try matching decompilation in the browser
- [libdragon](https://github.com/DragonMinded/libdragon): a modern open-source N64 SDK
