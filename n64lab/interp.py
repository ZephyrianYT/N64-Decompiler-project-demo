"""A simple MIPS interpreter: run a ROM one instruction at a time.

This is the opposite approach to recompiling.  Instead of translating code
ahead of time, it decodes and executes each instruction as it is reached,
which is how most emulators' CPU cores started out.  It is far too slow for
games, but it shows exactly what every instruction does:

    python -m n64lab trace hello.z64 --steps 40

It is written independently of the code generator, so the test suite can
compare the two: if the interpreter and the recompiled program disagree,
one of them has a bug.
"""

import math
import struct
import sys

from .mips import GPR_NAMES, decode

MASK64 = (1 << 64) - 1
MASK32 = 0xFFFFFFFF
RDRAM_SIZE = 0x800000
ISVIEWER = 0x13FF0000


def s32(value):
    """Sign-extend the low 32 bits into a 64-bit register value."""
    value &= MASK32
    return value | 0xFFFFFFFF00000000 if value & 0x80000000 else value


def signed(value, bits=64):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def f32_from_bits(bits):
    return struct.unpack(">f", struct.pack(">I", bits & MASK32))[0]


def f32_to_bits(value):
    try:
        return struct.unpack(">I", struct.pack(">f", value))[0]
    except OverflowError:  # too large for a float: becomes infinity
        return 0xFF800000 if value < 0 else 0x7F800000


def f64_from_bits(bits):
    return struct.unpack(">d", struct.pack(">Q", bits & MASK64))[0]


def f64_to_bits(value):
    return struct.unpack(">Q", struct.pack(">d", value))[0]


def round_float(value, mode):
    if math.isnan(value) or math.isinf(value):
        return None
    if mode == 1:
        return math.trunc(value)
    if mode == 2:
        return math.ceil(value)
    if mode == 3:
        return math.floor(value)
    return round(value)  # Python rounds halves to even, like the FPU


class Halt(Exception):
    pass


class Interpreter:
    def __init__(self, rom, symbols=None):
        self.rom = rom
        self.symbols = symbols or {}
        self.ram = bytearray(RDRAM_SIZE)
        self.gpr = [0] * 32
        self.hi = self.lo = 0
        self.fpr = [0] * 32          # 32-bit registers, FR=0 (doubles use even/odd pairs)
        self.fcr31 = 0x01000800
        self.cop0 = [0] * 32
        self.vi = [0] * 14
        self.pi = [0] * 13
        self.si = [0] * 7
        self.isviewer = bytearray(0x1000)
        self.output = []
        self.steps = 0
        self.decoded = {}
        self.writes = []             # memory writes during the current step, for tracing
        self.echo = None             # stream that receives program output as it is printed

        # Do what IPL3 does: copy 1 MiB of game code to the entry point.
        dest = rom.entry & 0x1FFFFFFF
        code = rom.data[0x1000:0x101000]
        self.ram[dest:dest + len(code)] = code
        for addr, value in ((0x300, 1), (0x308, 0xB0000000), (0x318, RDRAM_SIZE)):
            struct.pack_into(">I", self.ram, addr, value)
        self.gpr[29] = s32(0xA4001FF0)
        self.pc = rom.entry
        self.next_pc = rom.entry + 4

    # -- memory --------------------------------------------------------------

    @staticmethod
    def physical(addr):
        return addr & 0x1FFFFFFF

    def read(self, addr, size):
        p = self.physical(addr)
        if p + size <= RDRAM_SIZE:
            return int.from_bytes(self.ram[p:p + size], "big")
        if ISVIEWER + 0x20 <= p < ISVIEWER + 0x1000:
            off = p - ISVIEWER
            return int.from_bytes(self.isviewer[off:off + size], "big")
        if 0x10000000 <= p < 0x10000000 + len(self.rom.data):
            off = p - 0x10000000
            return int.from_bytes(self.rom.data[off:off + size].ljust(size, b"\0"), "big")
        word = self.read_register(p & ~3)
        shift = (4 - size - (p & 3)) * 8
        return (word >> shift) & ((1 << (size * 8)) - 1)

    def write(self, addr, size, value):
        p = self.physical(addr)
        value &= (1 << (size * 8)) - 1
        self.writes.append((addr, size, value))
        if p + size <= RDRAM_SIZE:
            self.ram[p:p + size] = value.to_bytes(size, "big")
        elif ISVIEWER + 0x20 <= p < ISVIEWER + 0x1000:
            off = p - ISVIEWER
            self.isviewer[off:off + size] = value.to_bytes(size, "big")
        elif size == 4:
            self.write_register(p, value)

    def read_register(self, p):
        if p == 0x04040010:
            return 1                                   # SP_STATUS: RSP halted
        if p == 0x04300004:
            return 0x02020102                          # MI_VERSION
        if 0x04400000 <= p < 0x04400038:
            if p == 0x04400010:                        # VI_V_CURRENT advances with time
                return (self.steps // 20) % 525 & ~1
            return self.vi[(p - 0x04400000) >> 2]
        return 0                                       # everything else reads as idle/zero

    def write_register(self, p, value):
        if p == ISVIEWER + 0x14:
            text = bytes(self.isviewer[0x20:0x20 + value]).decode("latin-1")
            self.output.append(text)
            if self.echo:
                self.echo.write(text)
        elif 0x04400000 <= p < 0x04400038:
            self.vi[(p - 0x04400000) >> 2] = value
        elif 0x04600000 <= p < 0x04600034:
            self.pi[(p - 0x04600000) >> 2] = value
            if p == 0x0460000C:                        # PI_WR_LEN: cartridge -> RDRAM DMA
                dram, cart, length = self.pi[0] & 0x7FFFFE, self.pi[1] & 0x0FFFFFFE, value + 1
                chunk = self.rom.data[cart:cart + length].ljust(length, b"\0")
                self.ram[dram:dram + length] = chunk[:max(0, RDRAM_SIZE - dram)]

    # -- execution ------------------------------------------------------------

    def run(self, max_steps=None, trace=False, out=None):
        """Run until BREAK, an error, or `max_steps`.  Sets self.stop_reason."""
        self.echo = out if not trace else None
        self.trace_out = out
        self.stop_reason = None
        try:
            while max_steps is None or self.steps < max_steps:
                self.step(trace)
        except Halt as reason:
            self.stop_reason = str(reason)
            if out:
                out.write("[stopped after %d instructions: %s]\n" % (self.steps, reason))
            return "".join(self.output)
        if out:
            out.write("[paused after %d instructions; use --steps for more]\n" % self.steps)
        return "".join(self.output)

    def fetch(self, pc):
        """Decode (once) the instruction at `pc` and find the method that executes it."""
        cached = self.decoded.get(pc)
        if cached is None:
            insn = decode(self.read(pc, 4), pc)
            cached = (insn, getattr(self, "op_" + insn.name.replace(".", "_"), None))
            self.decoded[pc] = cached
        return cached

    def step(self, trace=False):
        insn, handler = self.fetch(self.pc)
        before = list(self.gpr) if trace else None
        self.writes = []
        self.new_next = self.next_pc + 4
        self.skip_delay = False
        self.steps += 1
        if handler is None:
            raise Halt("instruction %s at 0x%08X is not supported by the interpreter" % (insn.name, insn.addr))
        try:
            handler(insn)
        finally:
            self.gpr[0] = 0
            if trace:
                self.print_trace(insn, before)
        if self.skip_delay:  # a branch-likely that was not taken skips its delay slot
            self.pc, self.next_pc = self.next_pc + 4, self.next_pc + 8
        else:
            self.pc, self.next_pc = self.next_pc, self.new_next

    def print_trace(self, insn, before):
        changes = ["%s=%016X" % (GPR_NAMES[r], self.gpr[r]) for r in range(1, 32) if self.gpr[r] != before[r]]
        changes += ["[%08X]=%0*X" % (a, s * 2, v) for a, s, v in self.writes]
        name = self.symbols.get(insn.addr)
        if name:
            self.trace_out.write("%s:\n" % name)
        line = "%08X  %08X  %s" % (insn.addr, insn.word, insn.text(self.symbols))
        self.trace_out.write("%-60s %s\n" % (line, "  ".join(changes)))

    def branch(self, taken, insn, link=False):
        if link:
            self.gpr[31] = s32(insn.addr + 8)
        if taken:
            self.new_next = insn.target
        elif insn.is_likely:
            self.skip_delay = True

    def reg(self, n):
        return self.gpr[n]

    def set(self, n, value):
        self.gpr[n] = value & MASK64

    # -- integer instructions ----------------------------------------------------------

    def op_sll(self, i): self.set(i.rd, s32(self.gpr[i.rt] << i.sa))
    def op_srl(self, i): self.set(i.rd, s32((self.gpr[i.rt] & MASK32) >> i.sa))
    def op_sra(self, i): self.set(i.rd, s32(signed(self.gpr[i.rt], 32) >> i.sa))
    def op_sllv(self, i): self.set(i.rd, s32(self.gpr[i.rt] << (self.gpr[i.rs] & 31)))
    def op_srlv(self, i): self.set(i.rd, s32((self.gpr[i.rt] & MASK32) >> (self.gpr[i.rs] & 31)))
    def op_srav(self, i): self.set(i.rd, s32(signed(self.gpr[i.rt], 32) >> (self.gpr[i.rs] & 31)))
    def op_dsll(self, i): self.set(i.rd, self.gpr[i.rt] << i.sa)
    def op_dsrl(self, i): self.set(i.rd, self.gpr[i.rt] >> i.sa)
    def op_dsra(self, i): self.set(i.rd, signed(self.gpr[i.rt]) >> i.sa)
    def op_dsll32(self, i): self.set(i.rd, self.gpr[i.rt] << (i.sa + 32))
    def op_dsrl32(self, i): self.set(i.rd, self.gpr[i.rt] >> (i.sa + 32))
    def op_dsra32(self, i): self.set(i.rd, signed(self.gpr[i.rt]) >> (i.sa + 32))
    def op_dsllv(self, i): self.set(i.rd, self.gpr[i.rt] << (self.gpr[i.rs] & 63))
    def op_dsrlv(self, i): self.set(i.rd, self.gpr[i.rt] >> (self.gpr[i.rs] & 63))
    def op_dsrav(self, i): self.set(i.rd, signed(self.gpr[i.rt]) >> (self.gpr[i.rs] & 63))

    def op_add(self, i): self.set(i.rd, s32(self.gpr[i.rs] + self.gpr[i.rt]))
    op_addu = op_add
    def op_sub(self, i): self.set(i.rd, s32(self.gpr[i.rs] - self.gpr[i.rt]))
    op_subu = op_sub
    def op_dadd(self, i): self.set(i.rd, self.gpr[i.rs] + self.gpr[i.rt])
    op_daddu = op_dadd
    def op_dsub(self, i): self.set(i.rd, self.gpr[i.rs] - self.gpr[i.rt])
    op_dsubu = op_dsub
    def op_and(self, i): self.set(i.rd, self.gpr[i.rs] & self.gpr[i.rt])
    def op_or(self, i): self.set(i.rd, self.gpr[i.rs] | self.gpr[i.rt])
    def op_xor(self, i): self.set(i.rd, self.gpr[i.rs] ^ self.gpr[i.rt])
    def op_nor(self, i): self.set(i.rd, ~(self.gpr[i.rs] | self.gpr[i.rt]))
    def op_slt(self, i): self.set(i.rd, int(signed(self.gpr[i.rs]) < signed(self.gpr[i.rt])))
    def op_sltu(self, i): self.set(i.rd, int(self.gpr[i.rs] < self.gpr[i.rt]))

    def op_addi(self, i): self.set(i.rt, s32(self.gpr[i.rs] + i.imm))
    op_addiu = op_addi
    def op_daddi(self, i): self.set(i.rt, self.gpr[i.rs] + i.imm)
    op_daddiu = op_daddi
    def op_slti(self, i): self.set(i.rt, int(signed(self.gpr[i.rs]) < i.imm))
    def op_sltiu(self, i): self.set(i.rt, int(self.gpr[i.rs] < (i.imm & MASK64)))
    def op_andi(self, i): self.set(i.rt, self.gpr[i.rs] & i.uimm)
    def op_ori(self, i): self.set(i.rt, self.gpr[i.rs] | i.uimm)
    def op_xori(self, i): self.set(i.rt, self.gpr[i.rs] ^ i.uimm)
    def op_lui(self, i): self.set(i.rt, s32(i.uimm << 16))

    def op_mult(self, i):
        p = signed(self.gpr[i.rs], 32) * signed(self.gpr[i.rt], 32)
        self.lo, self.hi = s32(p), s32(p >> 32)

    def op_multu(self, i):
        p = (self.gpr[i.rs] & MASK32) * (self.gpr[i.rt] & MASK32)
        self.lo, self.hi = s32(p), s32(p >> 32)

    def op_div(self, i):
        n, d = signed(self.gpr[i.rs], 32), signed(self.gpr[i.rt], 32)
        if d == 0:
            self.lo, self.hi = (1 if n < 0 else s32(-1)), s32(n)
        else:
            q = abs(n) // abs(d) * (1 if (n < 0) == (d < 0) else -1)  # C truncates toward zero
            self.lo, self.hi = s32(q), s32(n - q * d)

    def op_divu(self, i):
        n, d = self.gpr[i.rs] & MASK32, self.gpr[i.rt] & MASK32
        if d == 0:
            self.lo, self.hi = s32(-1), s32(n)
        else:
            self.lo, self.hi = s32(n // d), s32(n % d)

    def op_dmult(self, i):
        p = signed(self.gpr[i.rs]) * signed(self.gpr[i.rt])
        self.lo, self.hi = p & MASK64, (p >> 64) & MASK64

    def op_dmultu(self, i):
        p = self.gpr[i.rs] * self.gpr[i.rt]
        self.lo, self.hi = p & MASK64, p >> 64

    def op_ddiv(self, i):
        n, d = signed(self.gpr[i.rs]), signed(self.gpr[i.rt])
        if d == 0:
            self.lo, self.hi = (1 if n < 0 else MASK64), n & MASK64
        else:
            q = abs(n) // abs(d) * (1 if (n < 0) == (d < 0) else -1)
            self.lo, self.hi = q & MASK64, (n - q * d) & MASK64

    def op_ddivu(self, i):
        n, d = self.gpr[i.rs], self.gpr[i.rt]
        self.lo, self.hi = (MASK64, n) if d == 0 else (n // d, n % d)

    def op_mfhi(self, i): self.set(i.rd, self.hi)
    def op_mflo(self, i): self.set(i.rd, self.lo)
    def op_mthi(self, i): self.hi = self.gpr[i.rs]
    def op_mtlo(self, i): self.lo = self.gpr[i.rs]

    # -- memory instructions ------------------------------------------------------

    def ea(self, i):
        return (self.gpr[i.rs] + i.imm) & MASK32

    def op_lb(self, i): self.set(i.rt, signed(self.read(self.ea(i), 1), 8))
    def op_lbu(self, i): self.set(i.rt, self.read(self.ea(i), 1))
    def op_lh(self, i): self.set(i.rt, signed(self.read(self.ea(i), 2), 16))
    def op_lhu(self, i): self.set(i.rt, self.read(self.ea(i), 2))
    def op_lw(self, i): self.set(i.rt, s32(self.read(self.ea(i), 4)))
    op_ll = op_lw
    def op_lwu(self, i): self.set(i.rt, self.read(self.ea(i), 4))
    def op_ld(self, i): self.set(i.rt, self.read(self.ea(i), 8))
    def op_sb(self, i): self.write(self.ea(i), 1, self.gpr[i.rt])
    def op_sh(self, i): self.write(self.ea(i), 2, self.gpr[i.rt])
    def op_sw(self, i): self.write(self.ea(i), 4, self.gpr[i.rt])
    def op_sd(self, i): self.write(self.ea(i), 8, self.gpr[i.rt])

    def op_sc(self, i):
        self.op_sw(i)
        self.set(i.rt, 1)

    # Unaligned access, done byte by byte so it does not share logic with the C runtime.
    def op_lwl(self, i):
        addr = self.ea(i)
        value = self.gpr[i.rt] & MASK32
        for n in range(4 - (addr & 3)):
            shift = 24 - 8 * n
            value = (value & ~(0xFF << shift)) | (self.read(addr + n, 1) << shift)
        self.set(i.rt, s32(value))

    def op_lwr(self, i):
        addr = self.ea(i)
        value = self.gpr[i.rt] & MASK32
        for n in range((addr & 3) + 1):
            shift = 8 * n
            value = (value & ~(0xFF << shift)) | (self.read(addr - n, 1) << shift)
        self.set(i.rt, s32(value))

    def op_swl(self, i):
        addr = self.ea(i)
        for n in range(4 - (addr & 3)):
            self.write(addr + n, 1, self.gpr[i.rt] >> (24 - 8 * n))

    def op_swr(self, i):
        addr = self.ea(i)
        for n in range((addr & 3) + 1):
            self.write(addr - n, 1, self.gpr[i.rt] >> (8 * n))

    def op_ldl(self, i):
        addr = self.ea(i)
        value = self.gpr[i.rt]
        for n in range(8 - (addr & 7)):
            shift = 56 - 8 * n
            value = (value & ~(0xFF << shift)) | (self.read(addr + n, 1) << shift)
        self.set(i.rt, value)

    def op_ldr(self, i):
        addr = self.ea(i)
        value = self.gpr[i.rt]
        for n in range((addr & 7) + 1):
            shift = 8 * n
            value = (value & ~(0xFF << shift)) | (self.read(addr - n, 1) << shift)
        self.set(i.rt, value)

    def op_sdl(self, i):
        addr = self.ea(i)
        for n in range(8 - (addr & 7)):
            self.write(addr + n, 1, self.gpr[i.rt] >> (56 - 8 * n))

    def op_sdr(self, i):
        addr = self.ea(i)
        for n in range((addr & 7) + 1):
            self.write(addr - n, 1, self.gpr[i.rt] >> (8 * n))

    def op_cache(self, i): pass
    def op_sync(self, i): pass

    # -- control flow ---------------------------------------------------------------

    def op_j(self, i): self.new_next = i.target

    def op_jal(self, i):
        self.gpr[31] = s32(i.addr + 8)
        self.new_next = i.target

    def op_jr(self, i): self.new_next = self.gpr[i.rs] & MASK32

    def op_jalr(self, i):
        self.new_next = self.gpr[i.rs] & MASK32
        self.set(i.rd, s32(i.addr + 8))

    def op_beq(self, i): self.branch(self.gpr[i.rs] == self.gpr[i.rt], i)
    def op_bne(self, i): self.branch(self.gpr[i.rs] != self.gpr[i.rt], i)
    def op_blez(self, i): self.branch(signed(self.gpr[i.rs]) <= 0, i)
    def op_bgtz(self, i): self.branch(signed(self.gpr[i.rs]) > 0, i)
    def op_bltz(self, i): self.branch(signed(self.gpr[i.rs]) < 0, i)
    def op_bgez(self, i): self.branch(signed(self.gpr[i.rs]) >= 0, i)
    def op_bltzal(self, i): self.branch(signed(self.gpr[i.rs]) < 0, i, link=True)
    def op_bgezal(self, i): self.branch(signed(self.gpr[i.rs]) >= 0, i, link=True)
    op_beql, op_bnel, op_blezl, op_bgtzl = op_beq, op_bne, op_blez, op_bgtz
    op_bltzl, op_bgezl, op_bltzall, op_bgezall = op_bltz, op_bgez, op_bltzal, op_bgezal

    def trap(self, condition, i):
        if condition:
            raise Halt("trap (%s) at 0x%08X" % (i.name, i.addr))

    def op_teq(self, i): self.trap(self.gpr[i.rs] == self.gpr[i.rt], i)
    def op_tne(self, i): self.trap(self.gpr[i.rs] != self.gpr[i.rt], i)
    def op_tge(self, i): self.trap(signed(self.gpr[i.rs]) >= signed(self.gpr[i.rt]), i)
    def op_tgeu(self, i): self.trap(self.gpr[i.rs] >= self.gpr[i.rt], i)
    def op_tlt(self, i): self.trap(signed(self.gpr[i.rs]) < signed(self.gpr[i.rt]), i)
    def op_tltu(self, i): self.trap(self.gpr[i.rs] < self.gpr[i.rt], i)

    def op_break(self, i): raise Halt("BREAK at 0x%08X" % i.addr)
    def op_syscall(self, i): pass

    # -- coprocessor 0 ----------------------------------------------------------------

    def op_mfc0(self, i):
        value = self.steps // 2 if i.rd == 9 else self.cop0[i.rd]
        self.set(i.rt, s32(value))

    def op_mtc0(self, i): self.cop0[i.rd] = self.gpr[i.rt] & MASK32

    # -- coprocessor 1 (floating point) --------------------------------------------------

    def get_s(self, n): return f32_from_bits(self.fpr[n])
    def set_s(self, n, value): self.fpr[n] = f32_to_bits(value)

    def get_raw64(self, n): return (self.fpr[n | 1] << 32) | self.fpr[n & ~1]

    def set_raw64(self, n, value):
        self.fpr[n & ~1] = value & MASK32
        self.fpr[n | 1] = (value >> 32) & MASK32

    def get_d(self, n): return f64_from_bits(self.get_raw64(n))
    def set_d(self, n, value): self.set_raw64(n, f64_to_bits(value))

    def get(self, fmt, n):
        return {"s": self.get_s, "d": self.get_d}[fmt](n)

    def put(self, fmt, n, value):
        (self.set_s if fmt == "s" else self.set_d)(n, value)

    def op_mfc1(self, i): self.set(i.rt, s32(self.fpr[i.fs]))
    def op_mtc1(self, i): self.fpr[i.fs] = self.gpr[i.rt] & MASK32
    def op_dmfc1(self, i): self.set(i.rt, self.get_raw64(i.fs))
    def op_dmtc1(self, i): self.set_raw64(i.fs, self.gpr[i.rt])
    def op_cfc1(self, i): self.set(i.rt, s32(self.fcr31 if i.rd == 31 else 0xA00 if i.rd == 0 else 0))

    def op_ctc1(self, i):
        if i.rd == 31:
            self.fcr31 = self.gpr[i.rt] & MASK32

    def op_lwc1(self, i): self.fpr[i.ft] = self.read(self.ea(i), 4)
    def op_swc1(self, i): self.write(self.ea(i), 4, self.fpr[i.ft])
    def op_ldc1(self, i): self.set_raw64(i.ft, self.read(self.ea(i), 8))
    def op_sdc1(self, i): self.write(self.ea(i), 8, self.get_raw64(i.ft))

    def condition(self):
        return (self.fcr31 >> 23) & 1

    def op_bc1t(self, i): self.branch(self.condition() == 1, i)
    def op_bc1f(self, i): self.branch(self.condition() == 0, i)
    op_bc1tl, op_bc1fl = op_bc1t, op_bc1f

    def __getattr__(self, name):
        """Floating point arithmetic is generated from the mnemonic (op_add_s, op_c_lt_d...)."""
        if not name.startswith("op_"):
            raise AttributeError(name)
        parts = name[3:].split("_")
        if parts[0] == "c" and len(parts) == 3:
            return lambda i: self.fp_compare(parts[1], parts[2], i)
        if len(parts) == 2 and parts[0] in ("add", "sub", "mul", "div", "sqrt", "abs", "mov", "neg"):
            return lambda i: self.fp_arith(parts[0], parts[1], i)
        if len(parts) == 3 and parts[0] in ("cvt", "round", "trunc", "ceil", "floor"):
            return lambda i: self.fp_convert(parts[0], parts[1], parts[2], i)
        raise AttributeError(name)

    def fp_arith(self, op, fmt, i):
        if op == "mov":
            if fmt == "s":
                self.fpr[i.fd] = self.fpr[i.fs]
            else:
                self.set_raw64(i.fd, self.get_raw64(i.fs))
            return
        a = self.get(fmt, i.fs)
        b = self.get(fmt, i.ft)
        if op == "add":
            r = a + b
        elif op == "sub":
            r = a - b
        elif op == "mul":
            r = a * b
        elif op == "div":
            r = (a / b) if b else (math.nan if a == 0 or math.isnan(a) else math.copysign(math.inf, a) * math.copysign(1, b))
        elif op == "sqrt":
            r = math.sqrt(a) if a >= 0 else math.nan
        elif op == "abs":
            r = abs(a)
        else:
            r = -a
        self.put(fmt, i.fd, r)

    def fp_compare(self, cond, fmt, i):
        a, b = self.get(fmt, i.fs), self.get(fmt, i.ft)
        unordered = math.isnan(a) or math.isnan(b)
        base = ["f", "un", "eq", "ueq", "olt", "ult", "ole", "ule",
                "sf", "ngle", "seq", "ngl", "lt", "nge", "le", "ngt"].index(cond) & 7
        result = ((base & 1) and unordered) or ((base & 2) and a == b) or ((base & 4) and a < b)
        if result:
            self.fcr31 |= 1 << 23
        else:
            self.fcr31 &= ~(1 << 23)

    def fp_convert(self, op, to, frm, i):
        if frm in ("s", "d"):
            value = self.get(frm, i.fs)
        elif frm == "w":
            value = float(signed(self.fpr[i.fs], 32))
        else:
            value = float(signed(self.get_raw64(i.fs)))
        if to in ("s", "d"):
            self.put(to, i.fd, value)
            return
        mode = {"round": 0, "trunc": 1, "ceil": 2, "floor": 3}.get(op, self.fcr31 & 3)
        r = round_float(value, mode)
        if to == "w":
            self.fpr[i.fd] = (r & MASK32) if r is not None and -2**31 <= r < 2**31 else 0x80000000
        else:
            self.set_raw64(i.fd, (r & MASK64) if r is not None and -2**63 <= r < 2**63 else 1 << 63)


def run_rom(rom, max_steps=50_000_000):
    """Run until BREAK; return (everything the program printed, why it stopped)."""
    interp = Interpreter(rom)
    output = interp.run(max_steps=max_steps)
    return output, interp.stop_reason or "step limit reached"


if __name__ == "__main__":
    from .rom import Rom
    text, reason = run_rom(Rom.load(sys.argv[1]))
    sys.stdout.write(text)
    sys.stderr.write("[%s]\n" % reason)
