"""Command line interface: python -m n64lab <command> ..."""

import argparse
import os
import subprocess
import sys

from . import build as builder
from .rom import Rom, RomError


def load_config(args):
    config = builder.load_config(args.config)
    if getattr(args, "symbols", None):
        config["_symbols_file"] = args.symbols
    return config


def cmd_info(args):
    rom = Rom.load(args.rom)
    print(rom.describe())


def cmd_disasm(args):
    rom = Rom.load(args.rom)
    program = builder.make_program(rom, load_config(args))
    if args.function:
        addr = int(args.function, 0)
        func = program.functions.get(addr)
        if func is None:
            sys.exit("no function starts at 0x%08X (try without --function to list them)" % addr)
        print(builder.disassemble_function(program, func))
        return
    print("# %s - %s" % (rom.title, builder.summary(program)))
    for addr in sorted(program.functions):
        print(builder.disassemble_function(program, program.functions[addr]))


def cmd_functions(args):
    rom = Rom.load(args.rom)
    program = builder.make_program(rom, load_config(args))
    print("%-10s %-10s %6s  %-28s %s" % ("start", "end", "insns", "name", "found because"))
    for addr in sorted(program.functions):
        f = program.functions[addr]
        print("0x%08X 0x%08X %6d  %-28s %s" % (f.start, f.end, len(f.insns), f.name, f.reason))
        for w in f.warnings:
            print("%30s! %s" % ("", w))
    print("\n" + builder.summary(program))


def recompile(args):
    rom = Rom.load(args.rom)
    print(rom.describe())
    print()
    config = load_config(args)
    program = builder.make_program(rom, config)
    print("analysis: " + builder.summary(program))
    for note in program.notes:
        print("note: " + note)
    out = args.output or os.path.splitext(os.path.basename(args.rom))[0] + "_recomp"
    name = builder.write_project(program, out, config.get("name"))
    print("wrote C project to %s/" % out)
    exe = None
    if args.build or args.run:
        exe = builder.compile_project(out, name, target=args.target, cc=args.cc, opt=args.opt)
        print("built %s" % exe)
    return rom, exe


def cmd_recomp(args):
    _, exe = recompile(args)
    if args.run and exe:
        run_args = [os.path.abspath(exe), os.path.abspath(args.rom)] + args.run_args
        print("running: %s\n" % " ".join(run_args))
        sys.exit(subprocess.call(run_args))


def cmd_homebrew(args):
    from . import homebrew
    out = args.output or os.path.splitext(os.path.basename(args.sources[0]))[0] + ".z64"
    symbols = args.symbols or os.path.splitext(out)[0] + ".sym"
    homebrew.build(args.sources, out, title=args.title, opt=args.opt, symbols_out=symbols)
    print("built %s (function names in %s)" % (out, symbols))
    print("next: python -m n64lab recomp %s --symbols %s --run" % (out, symbols))


def cmd_trace(args):
    from .interp import Interpreter
    rom = Rom.load(args.rom)
    from .analysis import load_symbols
    interp = Interpreter(rom, symbols=load_symbols(args.symbols) if args.symbols else None)
    interp.run(max_steps=args.steps, trace=not args.quiet, out=sys.stdout)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="n64lab", description="Learn how N64 games work by recompiling them into C for Windows.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("info", help="show a ROM's header, boot chip and checksum")
    p.add_argument("rom")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("functions", help="list the functions the analyzer finds")
    p.add_argument("rom")
    p.add_argument("--config", help="JSON config with extra functions, names, segments")
    p.add_argument("--symbols", help="symbol file with `name = 0xADDR;` lines")
    p.set_defaults(func=cmd_functions)

    p = sub.add_parser("disasm", help="disassemble the code the recompiler would translate")
    p.add_argument("rom")
    p.add_argument("--function", help="only this function (address, e.g. 0x80000400)")
    p.add_argument("--config")
    p.add_argument("--symbols", help="symbol file with `name = 0xADDR;` lines")
    p.set_defaults(func=cmd_disasm)

    p = sub.add_parser("recomp", help="recompile a ROM to a C project (and optionally build it)")
    p.add_argument("rom")
    p.add_argument("-o", "--output", help="output directory (default: <rom>_recomp)")
    p.add_argument("--config")
    p.add_argument("--symbols", help="symbol file with `name = 0xADDR;` lines")
    p.add_argument("--build", action="store_true", help="compile the generated project")
    p.add_argument("--run", action="store_true", help="build, then run the program with this ROM")
    p.add_argument("--target", choices=["native", "windows"], default="native",
                   help="'windows' cross-compiles a .exe with MinGW when not on Windows")
    p.add_argument("--cc", help="C compiler to use")
    p.add_argument("--opt", default="-O1", help="optimization flag (default -O1)")
    p.add_argument("run_args", nargs="*", help="extra arguments for the program after --")
    p.set_defaults(func=cmd_recomp)

    p = sub.add_parser("homebrew", help="build a test ROM from C sources (needs clang + lld)")
    p.add_argument("sources", nargs="+")
    p.add_argument("-o", "--output")
    p.add_argument("--title", default="N64LAB TEST")
    p.add_argument("--opt", default="-O2")
    p.add_argument("--symbols", help="where to write function names (default: <output>.sym)")
    p.set_defaults(func=cmd_homebrew)

    p = sub.add_parser("trace", help="interpret a ROM instruction by instruction, printing each one")
    p.add_argument("rom")
    p.add_argument("--steps", type=int, default=200, help="stop after this many instructions")
    p.add_argument("--quiet", action="store_true", help="only print the program's own output")
    p.add_argument("--symbols", help="symbol file, so calls show function names")
    p.set_defaults(func=cmd_trace)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (RomError, OSError, RuntimeError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
