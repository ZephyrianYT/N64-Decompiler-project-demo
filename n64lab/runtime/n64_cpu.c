/*
 * n64_cpu.c - CPU behavior that is easier to write once in C than to
 * generate inline: multiply/divide edge cases, unaligned memory access,
 * float conversions, COP0, and indirect calls.
 */
#include <stdlib.h>
#include "n64_internal.h"

/* ---- multiply / divide ---------------------------------------------------- */

void op_mult(CPUState* cpu, uint64_t a, uint64_t b) {
    int64_t p = (int64_t)I32(a) * (int64_t)I32(b);
    cpu->lo = S32(p);
    cpu->hi = S32((uint64_t)p >> 32);
}

void op_multu(CPUState* cpu, uint64_t a, uint64_t b) {
    uint64_t p = (uint64_t)U32(a) * (uint64_t)U32(b);
    cpu->lo = S32(p);
    cpu->hi = S32(p >> 32);
}

/* Division by zero does not trap on MIPS; it produces these specific values. */
void op_div(CPUState* cpu, uint64_t a, uint64_t b) {
    int32_t n = I32(a), d = I32(b);
    if (d == 0) {
        cpu->lo = n < 0 ? 1 : S32(0xFFFFFFFF);
        cpu->hi = S32(n);
    } else if (n == INT32_MIN && d == -1) {
        cpu->lo = S32(n);
        cpu->hi = 0;
    } else {
        cpu->lo = S32(n / d);
        cpu->hi = S32(n % d);
    }
}

void op_divu(CPUState* cpu, uint64_t a, uint64_t b) {
    uint32_t n = U32(a), d = U32(b);
    if (d == 0) {
        cpu->lo = S32(0xFFFFFFFF);
        cpu->hi = S32(n);
    } else {
        cpu->lo = S32(n / d);
        cpu->hi = S32(n % d);
    }
}

/* 64x64 -> 128-bit multiply without compiler extensions, so MSVC works too. */
static void mul_u128(uint64_t a, uint64_t b, uint64_t* hi, uint64_t* lo) {
    uint64_t a_lo = (uint32_t)a, a_hi = a >> 32, b_lo = (uint32_t)b, b_hi = b >> 32;
    uint64_t p0 = a_lo * b_lo, p1 = a_lo * b_hi, p2 = a_hi * b_lo, p3 = a_hi * b_hi;
    uint64_t middle = (p0 >> 32) + (uint32_t)p1 + (uint32_t)p2;
    *lo = (middle << 32) | (uint32_t)p0;
    *hi = p3 + (p1 >> 32) + (p2 >> 32) + (middle >> 32);
}

void op_dmultu(CPUState* cpu, uint64_t a, uint64_t b) {
    mul_u128(a, b, &cpu->hi, &cpu->lo);
}

void op_dmult(CPUState* cpu, uint64_t a, uint64_t b) {
    uint64_t hi, lo;
    mul_u128(a, b, &hi, &lo);
    /* Signed correction: (a * b) mod 2^128 with two's complement inputs. */
    if ((int64_t)a < 0) hi -= b;
    if ((int64_t)b < 0) hi -= a;
    cpu->hi = hi;
    cpu->lo = lo;
}

void op_ddiv(CPUState* cpu, uint64_t a, uint64_t b) {
    int64_t n = (int64_t)a, d = (int64_t)b;
    if (d == 0) {
        cpu->lo = n < 0 ? 1 : UINT64_MAX;
        cpu->hi = a;
    } else if (n == INT64_MIN && d == -1) {
        cpu->lo = a;
        cpu->hi = 0;
    } else {
        cpu->lo = (uint64_t)(n / d);
        cpu->hi = (uint64_t)(n % d);
    }
}

void op_ddivu(CPUState* cpu, uint64_t a, uint64_t b) {
    if (b == 0) {
        cpu->lo = UINT64_MAX;
        cpu->hi = a;
    } else {
        cpu->lo = a / b;
        cpu->hi = a % b;
    }
}

/* ---- unaligned loads and stores ------------------------------------------------
 * Big-endian rules: LWL fills the high bytes of the register starting at
 * `addr`, LWR fills the low bytes ending at `addr`.  A compiler emits
 * `lwl r, 0(p); lwr r, 3(p)` to load a word from any address. */

uint64_t op_lwl(uint64_t rt, uint32_t addr) {
    unsigned shift = (addr & 3) * 8;
    uint32_t word = mem_read32(addr & ~3u);
    uint32_t keep = (1u << shift) - 1;
    return S32((word << shift) | (U32(rt) & keep));
}

uint64_t op_lwr(uint64_t rt, uint32_t addr) {
    unsigned shift = (3 - (addr & 3)) * 8;
    uint32_t word = mem_read32(addr & ~3u);
    uint32_t keep = ~(0xFFFFFFFFu >> shift);
    return S32((word >> shift) | (U32(rt) & keep));
}

void op_swl(uint32_t addr, uint64_t rt) {
    unsigned shift = (addr & 3) * 8;
    uint32_t word = mem_read32(addr & ~3u);
    uint32_t mask = 0xFFFFFFFFu >> shift;
    mem_write32(addr & ~3u, (word & ~mask) | (U32(rt) >> shift));
}

void op_swr(uint32_t addr, uint64_t rt) {
    unsigned shift = (3 - (addr & 3)) * 8;
    uint32_t word = mem_read32(addr & ~3u);
    uint32_t mask = 0xFFFFFFFFu << shift;
    mem_write32(addr & ~3u, (word & ~mask) | (U32(rt) << shift));
}

uint64_t op_ldl(uint64_t rt, uint32_t addr) {
    unsigned shift = (addr & 7) * 8;
    uint64_t dword = mem_read64(addr & ~7u);
    uint64_t keep = shift ? (1ull << shift) - 1 : 0;
    return (dword << shift) | (rt & keep);
}

uint64_t op_ldr(uint64_t rt, uint32_t addr) {
    unsigned shift = (7 - (addr & 7)) * 8;
    uint64_t dword = mem_read64(addr & ~7u);
    uint64_t keep = ~(UINT64_MAX >> shift);
    return (dword >> shift) | (rt & keep);
}

void op_sdl(uint32_t addr, uint64_t rt) {
    unsigned shift = (addr & 7) * 8;
    uint64_t dword = mem_read64(addr & ~7u);
    uint64_t mask = UINT64_MAX >> shift;
    mem_write64(addr & ~7u, (dword & ~mask) | (rt >> shift));
}

void op_sdr(uint32_t addr, uint64_t rt) {
    unsigned shift = (7 - (addr & 7)) * 8;
    uint64_t dword = mem_read64(addr & ~7u);
    uint64_t mask = UINT64_MAX << shift;
    mem_write64(addr & ~7u, (dword & ~mask) | (rt << shift));
}

/* ---- floating point ------------------------------------------------------------- */

static double round_by_mode(double v, int mode) {
    switch (mode) {
    case ROUND_TRUNC: return trunc(v);
    case ROUND_CEIL: return ceil(v);
    case ROUND_FLOOR: return floor(v);
    default: return nearbyint(v); /* round half to even, like the FPU */
    }
}

/* Out-of-range conversions raise an exception on the console; we return the
 * x86 "integer indefinite" value instead of invoking C undefined behavior. */
uint32_t FP_TO_W(double value, int mode) {
    double r = round_by_mode(value, mode);
    if (!(r >= -2147483648.0 && r <= 2147483647.0)) return 0x80000000u;
    return (uint32_t)(int32_t)r;
}

uint64_t FP_TO_L(double value, int mode) {
    double r = round_by_mode(value, mode);
    if (!(r >= -9223372036854775808.0 && r < 9223372036854775808.0)) return 0x8000000000000000ull;
    return (uint64_t)(int64_t)r;
}

int fcr_rounding_mode(const CPUState* cpu) { return cpu->fcr31 & 3; }

uint32_t fcr_read(const CPUState* cpu, int reg) {
    if (reg == 0) return 0x00000A00; /* FCR0: implementation/revision of the VR4300 FPU */
    if (reg == 31) return cpu->fcr31;
    return 0;
}

void fcr_write(CPUState* cpu, int reg, uint32_t value) {
    if (reg == 31) cpu->fcr31 = value;
}

/* ---- coprocessor 0 ----------------------------------------------------------------- */

enum { COP0_RANDOM = 1, COP0_COUNT = 9, COP0_PRID = 15, COP0_CONFIG = 16 };

uint32_t cop0_read(CPUState* cpu, int reg) {
    switch (reg) {
    case COP0_COUNT:
        /* Count ticks at half the 93.75 MHz CPU clock. */
        return (uint32_t)(n64_time_ns() * 46875 / 1000000);
    case COP0_RANDOM: return 31;
    case COP0_PRID: return 0x00000B22;
    default: return (uint32_t)cpu->cop0[reg];
    }
}

void cop0_write(CPUState* cpu, int reg, uint32_t value) {
    cpu->cop0[reg] = value;
}

/* ---- indirect control flow ----------------------------------------------------------- */

static const N64FunctionEntry* find_function(uint32_t addr) {
    size_t lo = 0, hi = n64_function_count;
    while (lo < hi) {
        size_t mid = (lo + hi) / 2;
        if (n64_functions[mid].vram == addr) return &n64_functions[mid];
        if (n64_functions[mid].vram < addr) lo = mid + 1;
        else hi = mid;
    }
    return NULL;
}

static N64Func lookup_or_die(uint32_t target, const char* how) {
    const N64FunctionEntry* entry = find_function(target);
    if (!entry && (target & 0xE0000000u) == 0xA0000000u) {
        entry = find_function(target - 0x20000000u); /* KSEG1 alias of KSEG0 code */
    }
    if (!entry) {
        n64_log("%s to 0x%08X, but no function was recompiled there.", how, target);
        n64_log("Add \"0x%08X\" to \"functions\" in the config and recompile.", target);
        n64_halt(3, "unknown indirect target");
    }
    return entry->func;
}

void n64_call(CPUState* cpu, uint32_t target) { lookup_or_die(target, "Indirect call")(cpu); }
void n64_jump(CPUState* cpu, uint32_t target) { lookup_or_die(target, "Indirect jump")(cpu); }

/* ---- --debug-calls: which recompiled functions are running ------------------------------
 * Written only by the game thread; read by whichever thread reports a hang.
 * The read can race with a call or return, which is fine for a diagnostic. */

#define CALL_STACK_MAX 1024
#define DEEP_STACK_WARNING 100000

static volatile uint32_t call_stack[CALL_STACK_MAX];
static volatile uint32_t call_depth;
static volatile int call_tracking;

void n64_debug_enter(uint32_t func) {
    uint32_t depth = call_depth;
    if (depth < CALL_STACK_MAX) call_stack[depth] = func;
    call_depth = depth + 1;
    call_tracking = 1;
    if (depth + 1 == DEEP_STACK_WARNING) {
        n64_log("warning: %u nested calls. Functions that jump to each other in a loop "
                "become C calls that never return, and this will eventually overflow the stack.",
                DEEP_STACK_WARNING);
    }
}

void n64_debug_leave(void) { call_depth--; }

void n64_print_call_stack(void) {
    if (!call_tracking) {
        n64_log("(recompile with --debug-calls to see which function the program was in)");
        return;
    }
    uint32_t depth = call_depth;
    uint32_t shown = depth < CALL_STACK_MAX ? depth : CALL_STACK_MAX;
    n64_log("call stack, innermost first (%u deep):", depth);
    for (uint32_t i = 0; i < shown && i < 24; i++) {
        uint32_t addr = call_stack[shown - 1 - i];
        const N64FunctionEntry* entry = find_function(addr);
        n64_log("  %2u  0x%08X  %s", i, addr, entry ? entry->name : "?");
    }
    if (shown > 24) n64_log("  ... %u more", depth - 24);
}

/* ---- exceptions and unsupported features --------------------------------------------- */

void n64_syscall(CPUState* cpu, uint32_t pc) {
    (void)cpu;
    n64_log("SYSCALL at 0x%08X ignored (exceptions are not emulated)", pc);
}

/* This runtime treats BREAK as "the program is finished", which makes test
 * programs easy to write.  A real console would jump to the exception vector. */
void n64_break(CPUState* cpu, uint32_t pc, uint32_t code) {
    (void)cpu;
    n64_log("BREAK %u at 0x%08X: program finished", code, pc);
    n64_halt((int)(code & 0xFF), "break");
}

void n64_trap(CPUState* cpu, uint32_t pc) {
    (void)cpu;
    n64_log("TRAP at 0x%08X", pc);
    n64_halt(4, "trap");
}

void n64_eret(CPUState* cpu, uint32_t pc) {
    (void)cpu;
    n64_log("ERET at 0x%08X: exception handlers are not emulated", pc);
}

void n64_unsupported(CPUState* cpu, uint32_t pc, const char* what) {
    static int warned;
    (void)cpu;
    if (warned++ < 8) n64_log("unsupported instruction %s at 0x%08X (ignored)", what, pc);
}

void n64_invalid_instruction(CPUState* cpu, uint32_t pc, uint32_t word) {
    (void)cpu;
    n64_log("invalid instruction 0x%08X at 0x%08X: probably data, not code", word, pc);
    n64_halt(5, "invalid instruction");
}

void n64_fell_off_end(CPUState* cpu, uint32_t pc) {
    (void)cpu;
    n64_log("execution ran past the end of a recompiled function at 0x%08X", pc);
    n64_halt(6, "fell off end");
}
