# Examples

Small N64 programs written in C that you can build into ROMs and push through
the recompiler. You need LLVM (`clang` and `ld.lld`) to build them. On Windows,
both the winlibs "with LLVM/Clang/LLD" build and the official LLVM installer
include them.

| Example | What it shows |
|---|---|
| `hello/hello.c` | Text output, recursion, a `switch` turned into a jump table inside `printf` |
| `bounce/bounce.c` | Drawing to the framebuffer, waiting for vblank, reading the controller |

```sh
python -m n64lab homebrew examples/hello/hello.c -o hello.z64
python -m n64lab recomp hello.z64 --symbols hello.sym --run
```

`homebrew` also writes `hello.sym`, which holds the real function names. Pass it
with `--symbols` so the generated C uses `fn_main` and `fn_fibonacci` instead of
`func_800015C0`. Leave it out to see what the recompiler works out on its own.

On Windows you can also drag `hello.z64` onto `n64lab.bat`. It picks up
`hello.sym` automatically if the file sits next to the ROM.

## Writing your own

Include `n64lab.h` (it's in `n64lab/homebrew/`). It gives you:

- `lab_printf` / `lab_puts`: print through the IS-Viewer debug port
- `lab_video_init`, `lab_wait_vblank` and `RGBA16()`: a 320x240 framebuffer
- `lab_read_pad()`: controller 1
- `lab_exit()`: stop the program (a `break` instruction)

When `main` returns, the startup code runs `break`, which the n64lab runtime
treats as "program finished".

These ROMs have an empty boot block (IPL3). That's fine for n64lab, but real
consoles and most emulators need a real one. Use
[libdragon](https://github.com/DragonMinded/libdragon) if you want your
homebrew to run there too.

## Config files

For ROMs you didn't build yourself, a JSON config can help the analyzer. See
`config.example.json`. Every field is optional:

| Field | Meaning |
|---|---|
| `name` | Name of the generated executable |
| (all fields) | Wherever a field takes a function, you can give its address or its name from the symbols |
| `functions` | Extra function start addresses the analyzer can't find (e.g. only reached through a pointer table) |
| `names` | Address → name, for functions you've identified |
| `symbols` | A symbol file (`name = 0x80001234;` per line, the format splat and decomp projects use) |
| `stubs` | Functions to replace with an empty body. Use a map (`{"device_ready": 1}`) to also set the return value in `$v0`. See "Stubs and hangs" in `docs/LEARNING.md` |
| `segments` | Extra code to recompile besides the 1 MiB boot segment, e.g. overlays loaded by DMA |

```sh
python -m n64lab recomp game.z64 --config game.json --build
```
