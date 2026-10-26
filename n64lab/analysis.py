"""Static analysis: find functions in a code segment and work out their shape.

A ROM is just bytes, with no symbol table, so the recompiler has to infer
where functions begin and end:

1. Start from the entry point (plus any addresses the user lists).
2. Sweep forward through each function.  Every `jal` target is another
   function start; every branch target is a label inside the function.
3. A function ends at `jr $ra` (return), at a tail-call `j`, or at an
   unconditional backward branch (an infinite loop), but only once no
   branch seen so far points past that spot.
4. `lui`/`addiu` pairs that build an address inside the code segment are
   probably function pointers (callbacks, thread entry points), so they are
   tried as function starts too.
5. Indirect jumps (`jr $reg`) are matched against the common switch-table
   pattern so the C output can use a `switch` instead of giving up.

The sweep repeats until the set of known functions stops changing, because
learning about a new function can turn a `j` that looked internal into a
tail call.
"""

import re
import struct
from dataclasses import dataclass, field

from .mips import decode

MAX_FUNCTION_INSNS = 0x10000
MAX_JUMP_TABLE = 1024


@dataclass
class Segment:
    name: str
    rom_start: int
    vram: int
    size: int

    def contains(self, vram):
        return self.vram <= vram < self.vram + self.size


@dataclass
class JumpTable:
    jr_addr: int
    table_addr: int
    register: int
    targets: list


@dataclass
class Function:
    start: int
    end: int                     # exclusive
    name: str
    reason: str                  # why we believe this is a function
    insns: list = field(default_factory=list)
    labels: set = field(default_factory=set)
    calls: set = field(default_factory=set)
    tail_calls: set = field(default_factory=set)
    jump_tables: dict = field(default_factory=dict)
    fallthrough: int = None      # next function if this one runs off its end
    warnings: list = field(default_factory=list)

    @property
    def size(self):
        return self.end - self.start


class Program:
    """The ROM's code, as segments and the functions found in them."""

    def __init__(self, rom, segments, symbols=None, extra_functions=(), stubs=()):
        self.rom = rom
        self.segments = segments
        self.symbols = dict(symbols or {})
        self.extra_functions = list(extra_functions)
        self.stubs = set(stubs)
        self.functions = {}
        self.notes = []
        self._decoded = {}

    # -- memory -----------------------------------------------------------

    def segment_for(self, vram):
        for seg in self.segments:
            if seg.contains(vram):
                return seg
        return None

    def read_u32(self, vram):
        seg = self.segment_for(vram)
        if seg is None:
            return None
        offset = seg.rom_start + (vram - seg.vram)
        if offset + 4 > len(self.rom.data):
            return None
        return struct.unpack_from(">I", self.rom.data, offset)[0]

    def insn_at(self, vram):
        if vram not in self._decoded:
            word = self.read_u32(vram)
            self._decoded[vram] = None if word is None else decode(word, vram)
        return self._decoded[vram]

    def is_code_address(self, vram):
        return vram % 4 == 0 and self.segment_for(vram) is not None

    def name_of(self, vram):
        return self.symbols.get(vram) or "func_%08X" % vram

    # -- discovery --------------------------------------------------------

    def analyze(self):
        """Find every function reachable from the entry point."""
        seeds = {self.rom.entry: "entry point"}
        for addr in self.extra_functions:
            seeds.setdefault(addr, "listed in config")
        for addr in self.symbols:
            if self.is_code_address(addr):
                seeds.setdefault(addr, "symbol file")

        known = dict(seeds)
        for _ in range(8):
            functions = self._discover(known)
            found = {start: f.reason for start, f in functions.items()}
            if set(found) == set(known):
                break
            for start, reason in found.items():
                known.setdefault(start, reason)
        self.functions = functions
        for addr in self.stubs:
            if addr not in self.functions:
                self.notes.append("stub 0x%08X is not a discovered function" % addr)
        return self

    def _discover(self, known):
        functions = {}
        queue = sorted(known.items())
        while queue:
            start, reason = queue.pop(0)
            if start in functions or not self.is_code_address(start):
                continue
            func = self._scan(start, reason, known)
            if func is None:
                continue
            functions[start] = func
            new = [(t, "called by %s" % func.name) for t in sorted(func.calls)]
            new += [(t, "tail call from %s" % func.name) for t in sorted(func.tail_calls)]
            if func.fallthrough is not None:
                new.append((func.fallthrough, "fallthrough from %s" % func.name))
            for addr in self._pointer_candidates(func):
                if addr not in known and addr not in functions and self._plausible(addr):
                    new.append((addr, "address taken in %s" % func.name))
            for addr, why in new:
                if addr not in known:
                    known[addr] = why
                if addr not in functions:
                    queue.append((addr, known[addr]))
        return functions

    def _scan(self, start, reason, known):
        func = Function(start, start, self.name_of(start), reason)
        furthest = start   # furthest internal branch target seen so far
        addr = start
        pending_end = None  # set when the current insn ends the function after its delay slot
        while len(func.insns) < MAX_FUNCTION_INSNS:
            if addr != start and addr in known and addr > furthest and pending_end is None:
                func.fallthrough = addr
                break
            insn = self.insn_at(addr)
            if insn is None:
                func.warnings.append("ran off the end of the segment at 0x%08X" % addr)
                break
            func.insns.append(insn)
            if pending_end is not None:
                addr += 4
                break
            if not insn.is_valid:
                func.warnings.append("invalid instruction 0x%08X at 0x%08X" % (insn.word, addr))
                addr += 4
                break

            name = insn.name
            ends = False
            if insn.is_branch and not insn.is_call:
                if self._is_internal(start, insn.target, known):
                    func.labels.add(insn.target)
                    furthest = max(furthest, insn.target)
                else:
                    func.tail_calls.add(insn.target)
                if insn.is_unconditional_branch and furthest <= addr:
                    ends = True
            elif insn.is_call and name != "jalr":
                func.calls.add(insn.target)
            elif name == "j":
                if self._is_internal(start, insn.target, known) and (
                        insn.target <= addr or insn.target not in known):
                    func.labels.add(insn.target)
                    furthest = max(furthest, insn.target)
                else:
                    func.tail_calls.add(insn.target)
                ends = furthest <= addr
            elif name == "jr":
                if insn.rs == 31:
                    ends = furthest <= addr
                else:
                    table = self._find_jump_table(func, insn, known)
                    if table:
                        func.jump_tables[addr] = table
                        for t in table.targets:
                            func.labels.add(t)
                            furthest = max(furthest, t)
                    else:
                        func.warnings.append(
                            "indirect jump at 0x%08X could not be resolved; "
                            "the runtime will look the target up" % addr)
                        ends = furthest <= addr
            elif name == "eret":
                ends = furthest <= addr
                if ends:
                    addr += 4
                    break

            if ends:
                pending_end = addr
            addr += 4
        func.end = addr
        return func

    def _is_internal(self, start, target, known):
        """Branch targets before the start, or at another function, are tail calls."""
        if target < start or not self.is_code_address(target):
            return False
        return target == start or target not in known

    def _find_jump_table(self, func, jr, known):
        """Match `lui rA, %hi(T); [addiu rA, rA, %lo(T)]; addu rB, rA, rI; lw rX, %lo(T)(rB); jr rX`."""
        insns = func.insns
        i = len(insns) - 1  # index of the jr itself
        load = self._last_writer(insns, i, jr.rs)
        if load is None or insns[load].name != "lw":
            return None
        lw = insns[load]
        add = self._last_writer(insns, load, lw.rs)
        if add is None or insns[add].name not in ("addu", "daddu"):
            return None
        base = None
        for reg in (insns[add].rs, insns[add].rt):
            value = self._constant(insns, add, reg)
            if value is not None:
                base = value
                break
        if base is None:
            return None
        table_addr = (base + lw.imm) & 0xFFFFFFFF
        count = self._table_size(insns, add, insns[add]) or MAX_JUMP_TABLE
        targets = []
        for n in range(count):
            word = self.read_u32(table_addr + 4 * n)
            if word is None or word % 4 or word < func.start or not self.is_code_address(word):
                break
            if word != func.start and word in known:
                break
            targets.append(word)
        return JumpTable(jr.addr, table_addr, jr.rs, targets) if targets else None

    def _table_size(self, insns, add_index, add):
        """Find the bounds check (`sltiu rC, rI, N`) that guards a switch, if any."""
        for reg in (add.rs, add.rt):
            j = self._last_writer(insns, add_index, reg)
            if j is None or insns[j].name != "sll" or insns[j].sa != 2:
                continue
            index_reg = insns[j].rt
            for k in range(j - 1, max(-1, j - 16), -1):
                insn = insns[k]
                if insn.name == "sltiu" and insn.rs == index_reg:
                    return insn.uimm
                if index_reg in writes(insn):
                    break
        return None

    @staticmethod
    def _last_writer(insns, before, reg, window=16):
        stop = -1 if window is None else max(-1, before - 1 - window)
        for j in range(before - 1, stop, -1):
            if reg in writes(insns[j]):
                return j
        return None

    def _constant(self, insns, before, reg):
        """Resolve `reg` to a constant if it was built by lui (+ addiu/ori).

        Compilers often load a table's address once, early in the function,
        so this searches all the way back to the function's start."""
        j = self._last_writer(insns, before, reg, window=None)
        if j is None:
            return None
        insn = insns[j]
        if insn.name == "lui":
            return (insn.uimm << 16) & 0xFFFFFFFF
        if insn.name in ("addiu", "ori"):
            hi = self._constant(insns, j, insn.rs)
            if hi is None:
                return None
            if insn.name == "addiu":
                return (hi + insn.imm) & 0xFFFFFFFF
            return hi | insn.uimm
        return None

    def _pointer_candidates(self, func):
        """Addresses inside the code segments built with `lui` + `addiu`/`ori`."""
        hi = {}
        for insn in func.insns:
            if insn.name == "lui":
                hi[insn.rt] = insn.uimm << 16
                continue
            if insn.name in ("addiu", "ori") and insn.rs in hi:
                lo = insn.imm if insn.name == "addiu" else insn.uimm
                addr = (hi[insn.rs] + lo) & 0xFFFFFFFF
                if self.is_code_address(addr) and not (func.start <= addr < func.end):
                    yield addr
            for reg in writes(insn):
                hi.pop(reg, None)

    def _plausible(self, addr):
        """Does `addr` look like the start of real code rather than data?"""
        first = self.insn_at(addr)
        if first is None or not first.is_valid or first.word == 0:
            return False
        for n in range(256):
            insn = self.insn_at(addr + 4 * n)
            if insn is None or not insn.is_valid:
                return False
            if insn.name == "jr" and insn.rs == 31:
                return True
        return False


# Registers written by an instruction ("hi"/"lo"/"fcc" and "f<n>" are used
# for the non-GPR destinations).
_WRITES_RD = {
    "sll", "srl", "sra", "sllv", "srlv", "srav", "mfhi", "mflo", "dsllv", "dsrlv", "dsrav",
    "add", "addu", "sub", "subu", "and", "or", "xor", "nor", "slt", "sltu",
    "dadd", "daddu", "dsub", "dsubu", "dsll", "dsrl", "dsra", "dsll32", "dsrl32", "dsra32", "jalr",
}
_WRITES_RT = {
    "addi", "addiu", "slti", "sltiu", "andi", "ori", "xori", "lui", "daddi", "daddiu",
    "ldl", "ldr", "lb", "lh", "lwl", "lw", "lbu", "lhu", "lwr", "lwu", "ll", "sc", "ld",
    "mfc0", "mfc1", "dmfc1", "cfc1",
}


def writes(insn):
    name = insn.name
    out = set()
    if name in _WRITES_RD:
        out.add(insn.rd)
    elif name in _WRITES_RT:
        out.add(insn.rt)
    elif name in ("mult", "multu", "div", "divu", "dmult", "dmultu", "ddiv", "ddivu"):
        out.update(("hi", "lo"))
    elif name in ("mthi", "mtlo"):
        out.add(name[2:])
    elif name == "jal" or name in ("bltzal", "bgezal", "bltzall", "bgezall"):
        out.add(31)
    elif name.startswith("c."):
        out.add("fcc")
    elif name in ("ctc1",):
        out.add("fcc")
    elif name in ("lwc1", "mtc1"):
        out.add("f%d" % insn.ft if name == "lwc1" else "f%d" % insn.fs)
    elif name in ("ldc1", "dmtc1"):
        reg = insn.ft if name == "ldc1" else insn.fs
        out.update(("f%d" % (reg & ~1), "f%d" % (reg | 1)))
    elif insn.op == 17 and insn.fmt:
        out.update(("f%d" % (insn.fd & ~1), "f%d" % (insn.fd | 1)))
    out.discard(0)
    return out


def reads(insn):
    """Registers an instruction reads (used to decide if a delay slot clobbers a branch condition)."""
    name = insn.name
    if name.startswith("bc1"):
        return {"fcc"}
    if insn.pattern.startswith("rs,rt") or name in _WRITES_RD and name not in (
            "mfhi", "mflo", "sll", "srl", "sra", "dsll", "dsrl", "dsra", "dsll32", "dsrl32", "dsra32"):
        return {insn.rs, insn.rt} - {0}
    if name in ("sll", "srl", "sra", "dsll", "dsrl", "dsra", "dsll32", "dsrl32", "dsra32"):
        return {insn.rt} - {0}
    return {insn.rs} - {0}


_SYMBOL_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*;?")


def load_symbols(path):
    """Read a splat/linker style symbol file: `name = 0x80001234;` per line."""
    symbols = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("//")[0]
            m = _SYMBOL_LINE.match(line)
            if m:
                symbols[int(m.group(2), 0)] = m.group(1)
    return symbols
