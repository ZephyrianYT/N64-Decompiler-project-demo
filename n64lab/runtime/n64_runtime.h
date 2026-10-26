/*
 * n64_runtime.h - everything recompiled code needs to run on a PC.
 *
 * The recompiler turns every MIPS function into a C function that takes a
 * CPUState*.  This header defines that state, plus the small macros the
 * generated code uses for memory access and arithmetic, so a line of
 * generated C maps closely onto one MIPS instruction.
 */
#ifndef N64_RUNTIME_H
#define N64_RUNTIME_H

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* ---------------------------------------------------------------------------
 * CPU state
 *
 * The VR4300 has 32 64-bit integer registers.  Most N64 code is 32-bit, and
 * the hardware keeps 32-bit results sign-extended to 64 bits, so we do too.
 * Floating point registers use the "FR=0" layout most games run with: 32
 * 32-bit registers, where a double occupies an even/odd pair.
 * ------------------------------------------------------------------------- */
typedef struct CPUState {
    union {
        uint64_t r[32];
        struct {
            uint64_t zero, at, v0, v1, a0, a1, a2, a3;
            uint64_t t0, t1, t2, t3, t4, t5, t6, t7;
            uint64_t s0, s1, s2, s3, s4, s5, s6, s7;
            uint64_t t8, t9, k0, k1, gp, sp, fp, ra;
        };
    };
    uint64_t hi, lo;
    uint32_t f[32];
    uint32_t fcr31;      /* FPU control/status; bit 23 holds the last compare result */
    uint64_t cop0[32];
} CPUState;

typedef void (*N64Func)(CPUState* cpu);

typedef struct N64FunctionEntry {
    uint32_t vram;
    N64Func func;
    const char* name;
} N64FunctionEntry;

/* Filled in by the generated game_info.c */
typedef struct N64GameInfo {
    const char* title;
    const char* game_code;
    uint32_t header_crc1, header_crc2;
    uint32_t entry;          /* where IPL3 copies the boot segment and jumps */
    uint32_t boot_rom_start; /* ROM offset of the boot segment (0x1000) */
    uint32_t boot_size;
} N64GameInfo;

extern const N64GameInfo n64_game;
extern const N64FunctionEntry n64_functions[];
extern const size_t n64_function_count;
void n64_game_entry(CPUState* cpu);

/* ---------------------------------------------------------------------------
 * Integer helpers
 * ------------------------------------------------------------------------- */
#define U32(x) ((uint32_t)(x))
#define I32(x) ((int32_t)(uint32_t)(x))
#define I64(x) ((int64_t)(x))
/* Truncate to 32 bits and sign-extend back to 64, like every 32-bit MIPS op. */
#define S32(x) ((uint64_t)(int64_t)(int32_t)(uint32_t)(x))

void op_mult(CPUState* cpu, uint64_t a, uint64_t b);
void op_multu(CPUState* cpu, uint64_t a, uint64_t b);
void op_div(CPUState* cpu, uint64_t a, uint64_t b);
void op_divu(CPUState* cpu, uint64_t a, uint64_t b);
void op_dmult(CPUState* cpu, uint64_t a, uint64_t b);
void op_dmultu(CPUState* cpu, uint64_t a, uint64_t b);
void op_ddiv(CPUState* cpu, uint64_t a, uint64_t b);
void op_ddivu(CPUState* cpu, uint64_t a, uint64_t b);

/* ---------------------------------------------------------------------------
 * Memory
 *
 * Addresses are 32-bit virtual addresses such as 0x80001234.  The runtime
 * maps them to physical memory: RDRAM, hardware registers, or the cartridge.
 * RDRAM is stored in the N64's big-endian byte order, so DMA is a memcpy and
 * each load assembles bytes in the right order.
 * ------------------------------------------------------------------------- */
uint8_t mem_read8(uint32_t addr);
uint16_t mem_read16(uint32_t addr);
uint32_t mem_read32(uint32_t addr);
uint64_t mem_read64(uint32_t addr);
void mem_write8(uint32_t addr, uint8_t value);
void mem_write16(uint32_t addr, uint16_t value);
void mem_write32(uint32_t addr, uint32_t value);
void mem_write64(uint32_t addr, uint64_t value);

#define ADDR(base, off) ((uint32_t)((base) + (off)))
#define LB(base, off)  ((uint64_t)(int64_t)(int8_t)mem_read8(ADDR(base, off)))
#define LBU(base, off) ((uint64_t)mem_read8(ADDR(base, off)))
#define LH(base, off)  ((uint64_t)(int64_t)(int16_t)mem_read16(ADDR(base, off)))
#define LHU(base, off) ((uint64_t)mem_read16(ADDR(base, off)))
#define LW(base, off)  S32(mem_read32(ADDR(base, off)))
#define LWU(base, off) ((uint64_t)mem_read32(ADDR(base, off)))
#define LD(base, off)  mem_read64(ADDR(base, off))
#define SB(base, off, v) mem_write8(ADDR(base, off), (uint8_t)(v))
#define SH(base, off, v) mem_write16(ADDR(base, off), (uint16_t)(v))
#define SW(base, off, v) mem_write32(ADDR(base, off), (uint32_t)(v))
#define SD(base, off, v) mem_write64(ADDR(base, off), (uint64_t)(v))

/* Unaligned loads/stores (lwl/lwr pairs read a word that straddles two words). */
uint64_t op_lwl(uint64_t rt, uint32_t addr);
uint64_t op_lwr(uint64_t rt, uint32_t addr);
uint64_t op_ldl(uint64_t rt, uint32_t addr);
uint64_t op_ldr(uint64_t rt, uint32_t addr);
void op_swl(uint32_t addr, uint64_t rt);
void op_swr(uint32_t addr, uint64_t rt);
void op_sdl(uint32_t addr, uint64_t rt);
void op_sdr(uint32_t addr, uint64_t rt);

/* ---------------------------------------------------------------------------
 * Floating point (COP1).  These macros assume the CPUState is named `cpu`.
 * ------------------------------------------------------------------------- */
static inline float fpr_get_s(const CPUState* cpu, int n) {
    float v;
    memcpy(&v, &cpu->f[n], sizeof v);
    return v;
}
static inline void fpr_set_s(CPUState* cpu, int n, float v) { memcpy(&cpu->f[n], &v, sizeof v); }
static inline uint64_t fpr_get64(const CPUState* cpu, int n) {
    return ((uint64_t)cpu->f[n | 1] << 32) | cpu->f[n & ~1];
}
static inline void fpr_set64(CPUState* cpu, int n, uint64_t v) {
    cpu->f[n & ~1] = (uint32_t)v;
    cpu->f[n | 1] = (uint32_t)(v >> 32);
}
static inline double fpr_get_d(const CPUState* cpu, int n) {
    uint64_t bits = fpr_get64(cpu, n);
    double v;
    memcpy(&v, &bits, sizeof v);
    return v;
}
static inline void fpr_set_d(CPUState* cpu, int n, double v) {
    uint64_t bits;
    memcpy(&bits, &v, sizeof bits);
    fpr_set64(cpu, n, bits);
}

#define F32(n) fpr_get_s(cpu, n)
#define F64(n) fpr_get_d(cpu, n)
#define SET_F32(n, v) fpr_set_s(cpu, n, (float)(v))
#define SET_F64(n, v) fpr_set_d(cpu, n, (double)(v))
#define FPR64(n) fpr_get64(cpu, n)
#define SET_FPR64(n, v) fpr_set64(cpu, n, (uint64_t)(v))
#define FCOND ((cpu->fcr31 >> 23) & 1)
#define SET_FCOND(c) (cpu->fcr31 = (c) ? (cpu->fcr31 | (1u << 23)) : (cpu->fcr31 & ~(1u << 23)))

enum { ROUND_NEAREST = 0, ROUND_TRUNC = 1, ROUND_CEIL = 2, ROUND_FLOOR = 3 };
uint32_t FP_TO_W(double value, int mode);
uint64_t FP_TO_L(double value, int mode);
int fcr_rounding_mode(const CPUState* cpu);
uint32_t fcr_read(const CPUState* cpu, int reg);
void fcr_write(CPUState* cpu, int reg, uint32_t value);

/* ---------------------------------------------------------------------------
 * Coprocessor 0 and things the recompiler cannot translate statically
 * ------------------------------------------------------------------------- */
uint32_t cop0_read(CPUState* cpu, int reg);
void cop0_write(CPUState* cpu, int reg, uint32_t value);

void n64_call(CPUState* cpu, uint32_t target);  /* call through a function pointer */
void n64_jump(CPUState* cpu, uint32_t target);  /* indirect tail jump */
void n64_syscall(CPUState* cpu, uint32_t pc);
void n64_break(CPUState* cpu, uint32_t pc, uint32_t code);
void n64_trap(CPUState* cpu, uint32_t pc);
void n64_eret(CPUState* cpu, uint32_t pc);
void n64_unsupported(CPUState* cpu, uint32_t pc, const char* what);
void n64_invalid_instruction(CPUState* cpu, uint32_t pc, uint32_t word);
void n64_fell_off_end(CPUState* cpu, uint32_t pc);

/* Only called by code recompiled with --debug-calls: a record of which
 * recompiled functions are running, printed when the program hangs or stops. */
void n64_debug_enter(uint32_t func);
void n64_debug_leave(void);

#endif
