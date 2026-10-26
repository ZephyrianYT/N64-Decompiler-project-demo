"""Translate analyzed MIPS functions into C.

Each MIPS function becomes one C function that takes the CPU state:

    void func_80000400(CPUState* cpu)

Registers live in `cpu` (cpu->a0, cpu->sp, ...).  Memory goes through
macros from the runtime (LW, SW, ...), so the generated code reads almost
like the assembly it came from, one C statement per instruction, with the
original instruction as a comment.

The main problem to solve is MIPS delay slots: the instruction after a
branch or jump runs before control moves.  For

    bnez  $v0, L1
    addiu $a0, $a0, 1      <- delay slot

the C output runs the delay slot first and then tests the condition.  If
the delay slot overwrites a register the condition reads, the condition is
saved in a temporary before the delay slot runs.
"""

import re

from .analysis import reads, writes
from .mips import GPR_NAMES

COMMENT_COLUMN = 48

FPU_COMPARE = {
    "f": "0",
    "un": "isnan(A) || isnan(B)",
    "eq": "A == B",
    "ueq": "A == B || isnan(A) || isnan(B)",
    "olt": "A < B",
    "ult": "!(A >= B)",
    "ole": "A <= B",
    "ule": "!(A > B)",
}
# The signaling compares only differ in which NaNs raise exceptions.
for _quiet, _signaling in (("f", "sf"), ("un", "ngle"), ("eq", "seq"), ("ueq", "ngl"),
                           ("olt", "lt"), ("ult", "nge"), ("ole", "le"), ("ule", "ngt")):
    FPU_COMPARE[_signaling] = FPU_COMPARE[_quiet]

ROUNDING = {"round": "ROUND_NEAREST", "trunc": "ROUND_TRUNC", "ceil": "ROUND_CEIL", "floor": "ROUND_FLOOR"}


def c_ident(name):
    out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    return out if out and not out[0].isdigit() else "_" + out


def func_ident(func):
    """C name for a recompiled function.

    Names from a symbol file get an `fn_` prefix so they can never collide
    with the C library or the runtime (a game's own `memcpy` or `main`)."""
    if func.name == "func_%08X" % func.start:
        return func.name
    return "fn_" + c_ident(func.name)


def gpr(n):
    return "0" if n == 0 else "cpu->" + GPR_NAMES[n]


def hexs(value):
    return "-0x%X" % -value if value < 0 else "0x%X" % value


def offset(expr, imm):
    if imm == 0:
        return expr
    return "%s %s 0x%X" % (expr, "-" if imm < 0 else "+", abs(imm))


def mem_args(insn):
    return "%s, %s" % (gpr(insn.rs), hexs(insn.imm))


class FunctionWriter:
    def __init__(self, program, func):
        self.program = program
        self.func = func
        self.lines = []
        self.name = func_ident(func)

    # -- output helpers ----------------------------------------------------

    def emit(self, code, insn=None, note="", indent=1):
        line = "    " * indent + code
        if insn is not None:
            comment = "// %08X: %s" % (insn.addr, insn.text(self.program.symbols))
            if note:
                comment += "  (%s)" % note
            if len(line) < COMMENT_COLUMN:
                line = line.ljust(COMMENT_COLUMN) + comment
            else:
                line += "  " + comment
        self.lines.append(line)

    def emit_label(self, addr):
        self.lines.append("L_%08X:" % addr)

    def call_name(self, target):
        func = self.program.functions.get(target)
        return func_ident(func) if func else None

    def transfer(self, target):
        """C code that continues execution at `target`: a goto or a tail call."""
        if target in self.func.labels:
            return "goto L_%08X;" % target
        name = self.call_name(target)
        if name:
            return "%s(cpu); return;" % name
        return "n64_jump(cpu, 0x%08X); return;" % target

    # -- whole function ------------------------------------------------------

    def write(self):
        func = self.func
        self.lines.append("// %s: 0x%08X-0x%08X, %d instructions" % (
            func.name, func.start, func.end, len(func.insns)))
        self.lines.append("// found because: %s" % func.reason)
        for warning in func.warnings:
            self.lines.append("// WARNING: %s" % warning)
        self.lines.append("void %s(CPUState* cpu) {" % self.name)

        if func.start in self.program.stubs:
            self.emit("// Stubbed out in the config: the original code is not run.")
            self.emit("return;")
            self.lines.append("}")
            return "\n".join(self.lines) + "\n"

        insns = func.insns
        labels = set(func.labels)
        # A label on a delay slot needs a label after it so the fall-through
        # path can skip over the second copy of the delay slot.
        for i, insn in enumerate(insns[:-1]):
            if insn.has_delay_slot and insns[i + 1].addr in labels:
                labels.add(insn.addr + 8)
        self.labels = labels

        i = 0
        while i < len(insns):
            insn = insns[i]
            if insn.addr in labels:
                self.emit_label(insn.addr)
            if insn.has_delay_slot and i + 1 < len(insns):
                delay = insns[i + 1]
                self.control(insn, delay)
                if delay.addr in labels:
                    if self.can_fall_through(insn):
                        self.emit("goto L_%08X;" % (delay.addr + 4))
                    self.emit_label(delay.addr)
                    self.plain(delay, "delay slot, entered by a branch")
                i += 2
            else:
                self.plain(insn)
                i += 1

        for addr in sorted(a for a in labels if a >= func.end):
            self.lines.append("L_%08X:;" % addr)
        last = insns[-1] if insns else None
        prev = insns[-2] if len(insns) > 1 else None
        ends_cleanly = prev is not None and prev.has_delay_slot and not self.can_fall_through(prev)
        if last is not None and last.name == "eret":
            ends_cleanly = True
        if func.fallthrough is not None:
            self.emit("%s(cpu); return;  // falls through into the next function" %
                      self.call_name(func.fallthrough))
        elif not ends_cleanly:
            self.emit("n64_fell_off_end(cpu, 0x%08X);" % func.end)
        self.lines.append("}")
        return "\n".join(self._drop_unused_labels(self.lines)) + "\n"

    @staticmethod
    def _drop_unused_labels(lines):
        """Remove labels nothing jumps to (e.g. targets of untranslatable branches)."""
        used = set(re.findall(r"goto (L_[0-9A-F]{8});", "\n".join(lines)))
        out = []
        for line in lines:
            m = re.match(r"(L_[0-9A-F]{8}):(;?)$", line)
            if m and m.group(1) not in used:
                if m.group(2):
                    out.append("    ;")
                continue
            out.append(line)
        return out

    @staticmethod
    def can_fall_through(insn):
        if insn.name in ("j", "jr"):
            return False
        if insn.is_branch and insn.is_unconditional_branch and not insn.is_call:
            return False
        return True

    # -- control flow ---------------------------------------------------------

    def condition(self, insn):
        name = insn.name[:-1] if insn.is_likely else insn.name
        rs, rt = gpr(insn.rs), gpr(insn.rt)
        signed = "(int64_t)" + rs
        return {
            "beq": "%s == %s" % (rs, rt), "bne": "%s != %s" % (rs, rt),
            "blez": signed + " <= 0", "bgtz": signed + " > 0",
            "bltz": signed + " < 0", "bgez": signed + " >= 0",
            "bltzal": signed + " < 0", "bgezal": signed + " >= 0",
            "bc1t": "FCOND", "bc1f": "!FCOND",
        }[name]

    def control(self, insn, delay):
        name = insn.name
        clobbered = bool(writes(delay) & reads(insn))
        if delay.has_delay_slot:
            self.emit("// WARNING: a jump in a delay slot is undefined behavior on MIPS")

        if insn.is_branch and not insn.is_call:
            action = self.transfer(insn.target)
            if insn.is_unconditional_branch:
                self.plain(delay, "delay slot")
                self.emit(action, insn)
            elif insn.is_likely:
                self.emit("if (%s) {" % self.condition(insn), insn, "likely: delay slot only runs if taken")
                self.plain(delay, "delay slot", indent=2)
                self.emit(action, indent=2)
                self.emit("}")
            elif clobbered:
                self.emit("{", insn)
                self.emit("int taken = %s;  // test before the delay slot changes it" %
                          self.condition(insn), indent=2)
                self.plain(delay, "delay slot", indent=2)
                self.emit("if (taken) %s" % action, indent=2)
                self.emit("}")
            else:
                self.plain(delay, "delay slot")
                self.emit("if (%s) %s" % (self.condition(insn), action), insn)
            return

        if insn.is_branch and insn.is_call:  # bltzal/bgezal and friends ("bal")
            callee = self.call_name(insn.target)
            call = "%s(cpu);" % callee if callee else "n64_call(cpu, 0x%08X);" % insn.target
            if insn.is_unconditional_branch:
                self.emit("cpu->ra = S32(0x%08X);" % (insn.addr + 8), insn)
                self.plain(delay, "delay slot")
                self.emit(call)
            else:
                self.emit("{", insn)
                self.emit("int taken = %s;" % self.condition(insn), indent=2)
                self.emit("cpu->ra = S32(0x%08X);" % (insn.addr + 8), indent=2)
                if insn.is_likely:
                    self.emit("if (taken) {", indent=2)
                    self.plain(delay, "delay slot", indent=3)
                    self.emit(call, indent=3)
                    self.emit("}", indent=2)
                else:
                    self.plain(delay, "delay slot", indent=2)
                    self.emit("if (taken) %s" % call, indent=2)
                self.emit("}")
            return

        if name == "jal":
            callee = self.call_name(insn.target)
            self.emit("cpu->ra = S32(0x%08X);" % (insn.addr + 8), insn, "call")
            self.plain(delay, "delay slot")
            if callee:
                self.emit("%s(cpu);" % callee)
            else:
                self.emit("n64_call(cpu, 0x%08X);" % insn.target)
        elif name == "j":
            self.plain(delay, "delay slot")
            self.emit(self.transfer(insn.target), insn)
        elif name == "jalr":
            self.emit("{", insn, "indirect call")
            self.emit("uint32_t target = U32(%s);" % gpr(insn.rs), indent=2)
            if insn.rd:
                self.emit("%s = S32(0x%08X);" % (gpr(insn.rd), insn.addr + 8), indent=2)
            self.plain(delay, "delay slot", indent=2)
            self.emit("n64_call(cpu, target);", indent=2)
            self.emit("}")
        elif name == "jr" and insn.rs == 31:
            self.plain(delay, "delay slot")
            self.emit("return;", insn)
        elif name == "jr":
            table = self.func.jump_tables.get(insn.addr)
            note = "switch via jump table at 0x%08X" % table.table_addr if table else "indirect jump"
            self.emit("{", insn, note)
            self.emit("uint32_t target = U32(%s);" % gpr(insn.rs), indent=2)
            self.plain(delay, "delay slot", indent=2)
            if table:
                self.emit("switch (target) {", indent=2)
                for t in sorted(set(table.targets)):
                    self.emit("case 0x%08X: goto L_%08X;" % (t, t), indent=3)
                self.emit("}", indent=2)
            self.emit("n64_jump(cpu, target); return;", indent=2)
            self.emit("}")

    # -- straight-line instructions ----------------------------------------------

    def plain(self, insn, note="", indent=1):
        for n, code in enumerate(self.translate(insn)):
            self.emit(code, insn if n == 0 else None, note, indent)

    def set_gpr(self, reg, expr, side_effects=False):
        if reg == 0:
            return "(void)%s;" % expr if side_effects else "// result discarded: writes to $zero"
        return "%s = %s;" % (gpr(reg), expr)

    def translate(self, insn):
        """Return the C statement(s) for one non-branch instruction."""
        n = insn.name
        rs, rt, rd = gpr(insn.rs), gpr(insn.rt), gpr(insn.rd)
        sa, imm, uimm = insn.sa, insn.imm, insn.uimm
        here = "0x%08X" % insn.addr

        if insn.word == 0:
            return [""]
        if not insn.is_valid:
            return ["n64_invalid_instruction(cpu, %s, 0x%08X);" % (here, insn.word)]
        if insn.has_delay_slot:
            return ["// WARNING: jump without a usable delay slot (in a delay slot, or at the end of the code) is not translated"]

        # Shifts.  32-bit results are always sign-extended into the 64-bit register.
        if n == "sll":
            return [self.set_gpr(insn.rd, "S32(U32(%s) << %d)" % (rt, sa))]
        if n == "srl":
            return [self.set_gpr(insn.rd, "S32(U32(%s) >> %d)" % (rt, sa))]
        if n == "sra":
            return [self.set_gpr(insn.rd, "S32(I32(%s) >> %d)" % (rt, sa))]
        if n == "sllv":
            return [self.set_gpr(insn.rd, "S32(U32(%s) << (%s & 31))" % (rt, rs))]
        if n == "srlv":
            return [self.set_gpr(insn.rd, "S32(U32(%s) >> (%s & 31))" % (rt, rs))]
        if n == "srav":
            return [self.set_gpr(insn.rd, "S32(I32(%s) >> (%s & 31))" % (rt, rs))]
        if n == "dsll":
            return [self.set_gpr(insn.rd, "%s << %d" % (rt, sa))]
        if n == "dsrl":
            return [self.set_gpr(insn.rd, "%s >> %d" % (rt, sa))]
        if n == "dsra":
            return [self.set_gpr(insn.rd, "(uint64_t)(I64(%s) >> %d)" % (rt, sa))]
        if n == "dsll32":
            return [self.set_gpr(insn.rd, "%s << %d" % (rt, sa + 32))]
        if n == "dsrl32":
            return [self.set_gpr(insn.rd, "%s >> %d" % (rt, sa + 32))]
        if n == "dsra32":
            return [self.set_gpr(insn.rd, "(uint64_t)(I64(%s) >> %d)" % (rt, sa + 32))]
        if n == "dsllv":
            return [self.set_gpr(insn.rd, "%s << (%s & 63)" % (rt, rs))]
        if n == "dsrlv":
            return [self.set_gpr(insn.rd, "%s >> (%s & 63)" % (rt, rs))]
        if n == "dsrav":
            return [self.set_gpr(insn.rd, "(uint64_t)(I64(%s) >> (%s & 63))" % (rt, rs))]

        # Register-register arithmetic.  (add/sub overflow exceptions are not modeled.)
        if n in ("add", "addu"):
            return [self.set_gpr(insn.rd, "S32(%s)" % rs if insn.rt == 0 else "S32(%s + %s)" % (rs, rt))]
        if n in ("sub", "subu"):
            return [self.set_gpr(insn.rd, "S32(%s - %s)" % (rs, rt))]
        if n in ("dadd", "daddu"):
            return [self.set_gpr(insn.rd, rs if insn.rt == 0 else "%s + %s" % (rs, rt))]
        if n in ("dsub", "dsubu"):
            return [self.set_gpr(insn.rd, "%s - %s" % (rs, rt))]
        if n == "and":
            return [self.set_gpr(insn.rd, "%s & %s" % (rs, rt))]
        if n == "or":
            return [self.set_gpr(insn.rd, rs if insn.rt == 0 else rt if insn.rs == 0 else "%s | %s" % (rs, rt))]
        if n == "xor":
            return [self.set_gpr(insn.rd, "%s ^ %s" % (rs, rt))]
        if n == "nor":
            return [self.set_gpr(insn.rd, "~(%s | %s)" % (rs, rt))]
        if n == "slt":
            return [self.set_gpr(insn.rd, "I64(%s) < I64(%s)" % (rs, rt))]
        if n == "sltu":
            return [self.set_gpr(insn.rd, "%s < %s" % (rs, rt))]

        # Multiply/divide write the HI and LO registers.
        if n in ("mult", "multu", "div", "divu", "dmult", "dmultu", "ddiv", "ddivu"):
            return ["op_%s(cpu, %s, %s);" % (n, rs, rt)]
        if n == "mfhi":
            return [self.set_gpr(insn.rd, "cpu->hi")]
        if n == "mflo":
            return [self.set_gpr(insn.rd, "cpu->lo")]
        if n == "mthi":
            return ["cpu->hi = %s;" % rs]
        if n == "mtlo":
            return ["cpu->lo = %s;" % rs]

        # Immediate arithmetic.
        if n in ("addi", "addiu"):
            if insn.rs == 0:
                return [self.set_gpr(insn.rt, hexs(imm) if imm >= 0 else "S32(%s)" % hexs(imm))]
            return [self.set_gpr(insn.rt, "S32(%s)" % offset(rs, imm))]
        if n in ("daddi", "daddiu"):
            return [self.set_gpr(insn.rt, offset(rs, imm) if insn.rs else "(uint64_t)(int64_t)%s" % hexs(imm))]
        if n == "slti":
            return [self.set_gpr(insn.rt, "I64(%s) < %s" % (rs, hexs(imm)))]
        if n == "sltiu":
            # The immediate is sign-extended first, then compared unsigned.
            limit = "0x%X" % imm if imm >= 0 else "(uint64_t)(int64_t)%s" % hexs(imm)
            return [self.set_gpr(insn.rt, "%s < %s" % (rs, limit))]
        if n == "andi":
            return [self.set_gpr(insn.rt, "%s & 0x%X" % (rs, uimm))]
        if n == "ori":
            return [self.set_gpr(insn.rt, "0x%X" % uimm if insn.rs == 0 else "%s | 0x%X" % (rs, uimm))]
        if n == "xori":
            return [self.set_gpr(insn.rt, "%s ^ 0x%X" % (rs, uimm))]
        if n == "lui":
            return [self.set_gpr(insn.rt, "S32(0x%X)" % (uimm << 16))]

        # Loads and stores.
        loads = {"lb": "LB", "lbu": "LBU", "lh": "LH", "lhu": "LHU", "lw": "LW", "lwu": "LWU",
                 "ld": "LD", "ll": "LW"}
        if n in loads:
            return [self.set_gpr(insn.rt, "%s(%s)" % (loads[n], mem_args(insn)), side_effects=True)]
        stores = {"sb": "SB", "sh": "SH", "sw": "SW", "sd": "SD"}
        if n in stores:
            return ["%s(%s, %s);" % (stores[n], mem_args(insn), rt)]
        if n == "sc":
            return ["SW(%s, %s);" % (mem_args(insn), rt), self.set_gpr(insn.rt, "1")]
        if n in ("lwl", "lwr", "ldl", "ldr"):
            return [self.set_gpr(insn.rt, "op_%s(%s, ADDR(%s))" % (n, rt, mem_args(insn)), side_effects=True)]
        if n in ("swl", "swr", "sdl", "sdr"):
            return ["op_%s(ADDR(%s), %s);" % (n, mem_args(insn), rt)]
        if n == "lwc1":
            return ["cpu->f[%d] = U32(LW(%s));" % (insn.ft, mem_args(insn))]
        if n == "swc1":
            return ["SW(%s, cpu->f[%d]);" % (mem_args(insn), insn.ft)]
        if n == "ldc1":
            return ["SET_FPR64(%d, LD(%s));" % (insn.ft, mem_args(insn))]
        if n == "sdc1":
            return ["SD(%s, FPR64(%d));" % (mem_args(insn), insn.ft)]
        if n == "cache":
            return ["// cache maintenance: nothing to do on a PC"]
        if n == "sync":
            return ["// sync: nothing to do on a PC"]

        # Traps and system calls.
        traps = {"tge": "I64(A) >= I64(B)", "tgeu": "A >= B", "tlt": "I64(A) < I64(B)",
                 "tltu": "A < B", "teq": "A == B", "tne": "A != B"}
        if n in traps:
            cond = traps[n].replace("A", rs).replace("B", rt)
            return ["if (%s) n64_trap(cpu, %s);" % (cond, here)]
        if n == "syscall":
            return ["n64_syscall(cpu, %s);" % here]
        if n == "break":
            return ["n64_break(cpu, %s, 0x%X);" % (here, (insn.word >> 6) & 0xFFFFF)]

        # Coprocessor 0 (system control).
        if n == "mfc0":
            return [self.set_gpr(insn.rt, "S32(cop0_read(cpu, %d))" % insn.rd)]
        if n == "mtc0":
            return ["cop0_write(cpu, %d, U32(%s));" % (insn.rd, rt)]
        if n in ("tlbr", "tlbwi", "tlbwr", "tlbp"):
            return ['n64_unsupported(cpu, %s, "%s (TLB)");' % (here, n)]
        if n == "eret":
            return ["n64_eret(cpu, %s); return;" % here]

        # Coprocessor 1 (floating point).
        return self.translate_fpu(insn)

    def translate_fpu(self, insn):
        n = insn.name
        rt = gpr(insn.rt)
        fs, ft, fd = insn.fs, insn.ft, insn.fd
        if n == "mfc1":
            return [self.set_gpr(insn.rt, "S32(cpu->f[%d])" % fs)]
        if n == "mtc1":
            return ["cpu->f[%d] = U32(%s);" % (fs, rt)]
        if n == "dmfc1":
            return [self.set_gpr(insn.rt, "FPR64(%d)" % fs)]
        if n == "dmtc1":
            return ["SET_FPR64(%d, %s);" % (fs, rt)]
        if n == "cfc1":
            return [self.set_gpr(insn.rt, "S32(fcr_read(cpu, %d))" % insn.rd)]
        if n == "ctc1":
            return ["fcr_write(cpu, %d, U32(%s));" % (insn.rd, rt)]

        base, _, fmt = n.rpartition(".")
        get = {"s": "F32", "d": "F64"}.get(fmt)
        put = {"s": "SET_F32", "d": "SET_F64"}.get(fmt)

        if base.startswith("c."):
            expr = FPU_COMPARE[base[2:]].replace("A", "%s(%d)" % (get, fs)).replace("B", "%s(%d)" % (get, ft))
            return ["SET_FCOND(%s);" % expr]
        ops = {"add": "+", "sub": "-", "mul": "*", "div": "/"}
        if base in ops:
            return ["%s(%d, %s(%d) %s %s(%d));" % (put, fd, get, fs, ops[base], get, ft)]
        if base == "sqrt":
            return ["%s(%d, %s(%s(%d)));" % (put, fd, "sqrtf" if fmt == "s" else "sqrt", get, fs)]
        if base == "abs":
            return ["%s(%d, %s(%s(%d)));" % (put, fd, "fabsf" if fmt == "s" else "fabs", get, fs)]
        if base == "neg":
            return ["%s(%d, -%s(%d));" % (put, fd, get, fs)]
        if base == "mov":
            if fmt == "s":
                return ["cpu->f[%d] = cpu->f[%d];" % (fd, fs)]
            return ["SET_FPR64(%d, FPR64(%d));" % (fd, fs)]

        # Conversions.  The source value as a C expression:
        source = {"s": "F32(%d)", "d": "F64(%d)", "w": "(int32_t)cpu->f[%d]",
                  "l": "(int64_t)FPR64(%d)"}[fmt] % fs
        if base == "cvt.s":
            return ["SET_F32(%d, (float)%s);" % (fd, source)]
        if base == "cvt.d":
            return ["SET_F64(%d, (double)%s);" % (fd, source)]
        mode, _, size = base.partition(".")
        if mode == "cvt":
            mode_expr = "fcr_rounding_mode(cpu)"
        else:
            mode_expr = ROUNDING[mode]
        if size == "w":
            return ["cpu->f[%d] = FP_TO_W(%s, %s);" % (fd, source, mode_expr)]
        if size == "l":
            return ["SET_FPR64(%d, FP_TO_L(%s, %s));" % (fd, source, mode_expr)]
        return ['n64_unsupported(cpu, 0x%08X, "%s");' % (insn.addr, n)]


def generate_function(program, func):
    return FunctionWriter(program, func).write()
