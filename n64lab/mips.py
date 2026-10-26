"""A table-driven decoder for the VR4300 CPU (MIPS III) used by the N64.

Every MIPS instruction is one 32-bit word.  The top 6 bits are the primary
opcode; a few opcodes (SPECIAL, REGIMM, COP0, COP1) select a second table
using another field.  The field layout is:

    R-type:  | op:6 | rs:5 | rt:5 | rd:5 | sa:5 | funct:6 |
    I-type:  | op:6 | rs:5 | rt:5 |      immediate:16      |
    J-type:  | op:6 |            target:26                 |

For COP1 (floating point) the same bits are read as
             | op:6 | fmt:5 | ft:5 | fs:5 | fd:5 | funct:6 |
"""

from dataclasses import dataclass

GPR_NAMES = [
    "zero", "at", "v0", "v1", "a0", "a1", "a2", "a3",
    "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
    "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
    "t8", "t9", "k0", "k1", "gp", "sp", "fp", "ra",
]

COP0_NAMES = [
    "Index", "Random", "EntryLo0", "EntryLo1", "Context", "PageMask", "Wired", "Reserved7",
    "BadVAddr", "Count", "EntryHi", "Compare", "Status", "Cause", "EPC", "PRId",
    "Config", "LLAddr", "WatchLo", "WatchHi", "XContext", "Reserved21", "Reserved22", "Reserved23",
    "Reserved24", "Reserved25", "PErr", "CacheErr", "TagLo", "TagHi", "ErrorEPC", "Reserved31",
]

# Operand layouts.  Each pattern is a comma-separated list of operand kinds
# that format_operands() knows how to print.
SPECIAL = {
    0: ("sll", "rd,rt,sa"), 2: ("srl", "rd,rt,sa"), 3: ("sra", "rd,rt,sa"),
    4: ("sllv", "rd,rt,rs"), 6: ("srlv", "rd,rt,rs"), 7: ("srav", "rd,rt,rs"),
    8: ("jr", "rs"), 9: ("jalr", "rd,rs"),
    12: ("syscall", ""), 13: ("break", ""), 15: ("sync", ""),
    16: ("mfhi", "rd"), 17: ("mthi", "rs"), 18: ("mflo", "rd"), 19: ("mtlo", "rs"),
    20: ("dsllv", "rd,rt,rs"), 22: ("dsrlv", "rd,rt,rs"), 23: ("dsrav", "rd,rt,rs"),
    24: ("mult", "rs,rt"), 25: ("multu", "rs,rt"), 26: ("div", "rs,rt"), 27: ("divu", "rs,rt"),
    28: ("dmult", "rs,rt"), 29: ("dmultu", "rs,rt"), 30: ("ddiv", "rs,rt"), 31: ("ddivu", "rs,rt"),
    32: ("add", "rd,rs,rt"), 33: ("addu", "rd,rs,rt"), 34: ("sub", "rd,rs,rt"), 35: ("subu", "rd,rs,rt"),
    36: ("and", "rd,rs,rt"), 37: ("or", "rd,rs,rt"), 38: ("xor", "rd,rs,rt"), 39: ("nor", "rd,rs,rt"),
    42: ("slt", "rd,rs,rt"), 43: ("sltu", "rd,rs,rt"),
    44: ("dadd", "rd,rs,rt"), 45: ("daddu", "rd,rs,rt"), 46: ("dsub", "rd,rs,rt"), 47: ("dsubu", "rd,rs,rt"),
    48: ("tge", "rs,rt"), 49: ("tgeu", "rs,rt"), 50: ("tlt", "rs,rt"), 51: ("tltu", "rs,rt"),
    52: ("teq", "rs,rt"), 54: ("tne", "rs,rt"),
    56: ("dsll", "rd,rt,sa"), 58: ("dsrl", "rd,rt,sa"), 59: ("dsra", "rd,rt,sa"),
    60: ("dsll32", "rd,rt,sa"), 62: ("dsrl32", "rd,rt,sa"), 63: ("dsra32", "rd,rt,sa"),
}

REGIMM = {
    0: ("bltz", "rs,branch"), 1: ("bgez", "rs,branch"),
    2: ("bltzl", "rs,branch"), 3: ("bgezl", "rs,branch"),
    16: ("bltzal", "rs,branch"), 17: ("bgezal", "rs,branch"),
    18: ("bltzall", "rs,branch"), 19: ("bgezall", "rs,branch"),
}

OPCODES = {
    2: ("j", "target"), 3: ("jal", "target"),
    4: ("beq", "rs,rt,branch"), 5: ("bne", "rs,rt,branch"),
    6: ("blez", "rs,branch"), 7: ("bgtz", "rs,branch"),
    8: ("addi", "rt,rs,imm"), 9: ("addiu", "rt,rs,imm"),
    10: ("slti", "rt,rs,imm"), 11: ("sltiu", "rt,rs,imm"),
    12: ("andi", "rt,rs,uimm"), 13: ("ori", "rt,rs,uimm"), 14: ("xori", "rt,rs,uimm"),
    15: ("lui", "rt,uimm"),
    20: ("beql", "rs,rt,branch"), 21: ("bnel", "rs,rt,branch"),
    22: ("blezl", "rs,branch"), 23: ("bgtzl", "rs,branch"),
    24: ("daddi", "rt,rs,imm"), 25: ("daddiu", "rt,rs,imm"),
    26: ("ldl", "rt,mem"), 27: ("ldr", "rt,mem"),
    32: ("lb", "rt,mem"), 33: ("lh", "rt,mem"), 34: ("lwl", "rt,mem"), 35: ("lw", "rt,mem"),
    36: ("lbu", "rt,mem"), 37: ("lhu", "rt,mem"), 38: ("lwr", "rt,mem"), 39: ("lwu", "rt,mem"),
    40: ("sb", "rt,mem"), 41: ("sh", "rt,mem"), 42: ("swl", "rt,mem"), 43: ("sw", "rt,mem"),
    44: ("sdl", "rt,mem"), 45: ("sdr", "rt,mem"), 46: ("swr", "rt,mem"), 47: ("cache", "op,mem"),
    48: ("ll", "rt,mem"), 49: ("lwc1", "ft,mem"), 53: ("ldc1", "ft,mem"), 55: ("ld", "rt,mem"),
    56: ("sc", "rt,mem"), 57: ("swc1", "ft,mem"), 61: ("sdc1", "ft,mem"), 63: ("sd", "rt,mem"),
}

FPU_FORMATS = {16: "s", 17: "d", 20: "w", 21: "l"}

FPU_OPS = {
    0: ("add", "fd,fs,ft"), 1: ("sub", "fd,fs,ft"), 2: ("mul", "fd,fs,ft"), 3: ("div", "fd,fs,ft"),
    4: ("sqrt", "fd,fs"), 5: ("abs", "fd,fs"), 6: ("mov", "fd,fs"), 7: ("neg", "fd,fs"),
    8: ("round.l", "fd,fs"), 9: ("trunc.l", "fd,fs"), 10: ("ceil.l", "fd,fs"), 11: ("floor.l", "fd,fs"),
    12: ("round.w", "fd,fs"), 13: ("trunc.w", "fd,fs"), 14: ("ceil.w", "fd,fs"), 15: ("floor.w", "fd,fs"),
    32: ("cvt.s", "fd,fs"), 33: ("cvt.d", "fd,fs"), 36: ("cvt.w", "fd,fs"), 37: ("cvt.l", "fd,fs"),
}

FPU_CONDITIONS = ["f", "un", "eq", "ueq", "olt", "ult", "ole", "ule",
                  "sf", "ngle", "seq", "ngl", "lt", "nge", "le", "ngt"]

BRANCHES = {
    "beq", "bne", "blez", "bgtz", "beql", "bnel", "blezl", "bgtzl",
    "bltz", "bgez", "bltzl", "bgezl", "bltzal", "bgezal", "bltzall", "bgezall",
    "bc1f", "bc1t", "bc1fl", "bc1tl",
}
# "Likely" branches only execute their delay slot when the branch is taken.
LIKELY = {"beql", "bnel", "blezl", "bgtzl", "bltzl", "bgezl", "bltzall", "bgezall", "bc1fl", "bc1tl"}
LINKING_BRANCHES = {"bltzal", "bgezal", "bltzall", "bgezall"}


@dataclass
class Insn:
    addr: int
    word: int
    name: str        # mnemonic, "invalid" if the word does not decode
    pattern: str     # operand layout, see the tables above
    op: int
    rs: int
    rt: int
    rd: int
    sa: int
    funct: int
    imm: int         # immediate, sign-extended
    uimm: int        # immediate, zero-extended
    target: int      # absolute target of j/jal or a branch, else 0
    fmt: str = ""    # FPU format letter for COP1 arithmetic

    # FPU register fields are the same bits as the integer ones.
    @property
    def ft(self):
        return self.rt

    @property
    def fs(self):
        return self.rd

    @property
    def fd(self):
        return self.sa

    @property
    def is_branch(self):
        return self.name in BRANCHES

    @property
    def is_likely(self):
        return self.name in LIKELY

    @property
    def is_jump(self):
        return self.name in ("j", "jal", "jr", "jalr")

    @property
    def has_delay_slot(self):
        """Branches and jumps execute the following instruction before transferring control."""
        return self.is_branch or self.is_jump

    @property
    def is_call(self):
        return self.name in ("jal", "jalr") or self.name in LINKING_BRANCHES

    @property
    def is_unconditional_branch(self):
        """`b label` is encoded as `beq $zero, $zero, label`."""
        return self.name in ("beq", "beql") and self.rs == 0 and self.rt == 0 or \
            self.name in ("bgez", "bgezal") and self.rs == 0

    @property
    def is_valid(self):
        return self.name != "invalid"

    @property
    def is_nop(self):
        return self.word == 0

    def text(self, symbols=None):
        """Return assembly text, e.g. `addiu $sp, $sp, -0x18`."""
        name, operands = self._pretty()
        ops = format_operands(self, operands, symbols)
        return ("%-8s%s" % (name, ops)).rstrip()

    def _pretty(self):
        """Use the common assembler aliases (nop, move, b, beqz...)."""
        if self.word == 0:
            return "nop", ""
        if self.name in ("addu", "or", "daddu") and self.rt == 0:
            return "move", "rd,rs"
        if self.is_unconditional_branch and self.name == "beq":
            return "b", "branch"
        if self.name in ("beq", "bne") and self.rt == 0:
            return self.name + "z", "rs,branch"
        return self.name, self.pattern


def _hex(value):
    return "-0x%X" % -value if value < 0 else "0x%X" % value


def format_operands(insn, pattern, symbols=None):
    out = []
    for kind in pattern.split(",") if pattern else []:
        if kind in ("rs", "rt", "rd"):
            out.append("$" + GPR_NAMES[getattr(insn, kind)])
        elif kind in ("fs", "ft", "fd"):
            out.append("$f%d" % getattr(insn, kind))
        elif kind == "sa":
            out.append(str(insn.sa))
        elif kind == "imm":
            out.append(_hex(insn.imm))
        elif kind == "uimm":
            out.append("0x%X" % insn.uimm)
        elif kind == "mem":
            out.append("%s($%s)" % (_hex(insn.imm), GPR_NAMES[insn.rs]))
        elif kind == "op":
            out.append("0x%X" % insn.rt)
        elif kind == "cop0":
            out.append("$" + COP0_NAMES[insn.rd])
        elif kind == "fcr":
            out.append("$%d" % insn.rd)
        elif kind in ("branch", "target"):
            name = symbols.get(insn.target) if symbols else None
            out.append(name or "0x%08X" % insn.target)
    return ", ".join(out)


def decode(word, addr):
    """Decode one instruction word located at virtual address `addr`."""
    op = word >> 26
    rs = (word >> 21) & 31
    rt = (word >> 16) & 31
    rd = (word >> 11) & 31
    sa = (word >> 6) & 31
    funct = word & 63
    uimm = word & 0xFFFF
    imm = uimm - 0x10000 if uimm & 0x8000 else uimm
    target = 0
    fmt = ""
    entry = None

    if op == 0:
        entry = SPECIAL.get(funct)
    elif op == 1:
        entry = REGIMM.get(rt)
    elif op == 16:
        if rs == 0:
            entry = ("mfc0", "rt,cop0")
        elif rs == 4:
            entry = ("mtc0", "rt,cop0")
        elif rs == 16:
            entry = {1: ("tlbr", ""), 2: ("tlbwi", ""), 6: ("tlbwr", ""),
                     8: ("tlbp", ""), 24: ("eret", "")}.get(funct)
    elif op == 17:
        if rs in (0, 1, 2, 4, 5, 6):
            entry = {0: ("mfc1", "rt,fs"), 1: ("dmfc1", "rt,fs"), 2: ("cfc1", "rt,fcr"),
                     4: ("mtc1", "rt,fs"), 5: ("dmtc1", "rt,fs"), 6: ("ctc1", "rt,fcr")}[rs]
        elif rs == 8:
            entry = (("bc1f", "bc1t", "bc1fl", "bc1tl")[rt & 3], "branch")
        elif rs in FPU_FORMATS:
            fmt = FPU_FORMATS[rs]
            if funct >= 48 and fmt in "sd":
                entry = ("c.%s.%s" % (FPU_CONDITIONS[funct - 48], fmt), "fs,ft")
            elif funct in FPU_OPS:
                base, pattern = FPU_OPS[funct]
                # Integer formats (w, l) can only be converted to s or d, and
                # nothing converts to its own format.
                to_float = base in ("cvt.s", "cvt.d")
                if (fmt in "sd" or to_float) and base != "cvt." + fmt:
                    entry = ("%s.%s" % (base, fmt), pattern)
    else:
        entry = OPCODES.get(op)

    if entry is None:
        return Insn(addr, word, "invalid", "", op, rs, rt, rd, sa, funct, imm, uimm, 0)

    name, pattern = entry
    if pattern.endswith("target"):
        # j/jal keep the top 4 bits of the delay-slot address (the "region").
        target = ((addr + 4) & 0xF0000000) | ((word & 0x3FFFFFF) << 2)
    elif pattern.endswith("branch"):
        target = (addr + 4 + (imm << 2)) & 0xFFFFFFFF
    return Insn(addr, word, name, pattern, op, rs, rt, rd, sa, funct, imm, uimm, target, fmt)
