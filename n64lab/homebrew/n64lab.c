/*
 * n64lab.c - hardware access for bare-metal test programs (see n64lab.h).
 * Also provides the few C library functions the compiler may call on its
 * own (memcpy, memset, 64-bit division helpers).
 */
#include "n64lab.h"

/* ---- printing through the IS-Viewer debug port ---------------------------------
 * The IS-Viewer was a development cartridge with a text buffer in ROM space.
 * Emulators (and n64lab's runtime) print whatever is written there. */

#define ISVIEWER_LEN  0xB3FF0014
#define ISVIEWER_BUF  0xB3FF0020

static void isviewer_write(const char* s, int len) {
    for (int i = 0; i < len; i += 4) {
        unsigned int word = 0;
        for (int j = 0; j < 4; j++) {
            word = (word << 8) | (unsigned char)(i + j < len ? s[i + j] : 0);
        }
        IO32(ISVIEWER_BUF + i) = word;
    }
    IO32(ISVIEWER_LEN) = (unsigned int)len;
}

void lab_puts(const char* s) {
    int len = 0;
    while (s[len]) len++;
    isviewer_write(s, len);
}

typedef struct {
    char buf[256];
    int len;
} Out;

static void put(Out* o, char c) {
    if (o->len == (int)sizeof o->buf) {
        isviewer_write(o->buf, o->len);
        o->len = 0;
    }
    o->buf[o->len++] = c;
}

static void put_number(Out* o, unsigned int value, unsigned int base, int upper, int negative,
                       int width, char pad) {
    char digits[12];
    int n = 0;
    const char* set = upper ? "0123456789ABCDEF" : "0123456789abcdef";
    do {
        digits[n++] = set[value % base];
        value /= base;
    } while (value);
    int total = n + negative;
    if (negative && pad == '0') put(o, '-');
    for (; total < width; total++) put(o, pad);
    if (negative && pad != '0') put(o, '-');
    while (n) put(o, digits[--n]);
}

/* Supports %d %u %x %X %c %s %% with optional zero padding and width. */
void lab_printf(const char* fmt, ...) {
    Out o;
    va_list args;
    o.len = 0;
    va_start(args, fmt);
    for (; *fmt; fmt++) {
        if (*fmt != '%') {
            put(&o, *fmt);
            continue;
        }
        char pad = ' ';
        int width = 0;
        fmt++;
        if (*fmt == '0') {
            pad = '0';
            fmt++;
        }
        while (*fmt >= '0' && *fmt <= '9') width = width * 10 + (*fmt++ - '0');
        switch (*fmt) {
        case 'd': {
            int v = va_arg(args, int);
            put_number(&o, v < 0 ? 0u - (unsigned int)v : (unsigned int)v, 10, 0, v < 0, width, pad);
            break;
        }
        case 'u': put_number(&o, va_arg(args, unsigned int), 10, 0, 0, width, pad); break;
        case 'x': put_number(&o, va_arg(args, unsigned int), 16, 0, 0, width, pad); break;
        case 'X': put_number(&o, va_arg(args, unsigned int), 16, 1, 0, width, pad); break;
        case 'c': put(&o, (char)va_arg(args, int)); break;
        case 's': {
            const char* s = va_arg(args, const char*);
            int len = 0;
            while (s[len]) len++;
            for (; len < width; len++) put(&o, ' ');
            while (*s) put(&o, *s++);
            break;
        }
        case '%': put(&o, '%'); break;
        default: put(&o, '?'); break;
        }
    }
    va_end(args);
    if (o.len) isviewer_write(o.buf, o.len);
}

/* ---- video ----------------------------------------------------------------------- */

#define VI_BASE 0xA4400000

void lab_video_init(void* framebuffer, int bits_per_pixel) {
    /* Standard NTSC 320x240 timings (the values libultra's osViModeNtscLpn1 uses). */
    IO32(VI_BASE + 0x00) = bits_per_pixel == 32 ? 0x00003203 : 0x00003202; /* CTRL: pixel size */
    IO32(VI_BASE + 0x04) = (unsigned int)framebuffer & 0x00FFFFFF;        /* ORIGIN */
    IO32(VI_BASE + 0x08) = 320;                                           /* WIDTH */
    IO32(VI_BASE + 0x0C) = 2;                                             /* V_INTR */
    IO32(VI_BASE + 0x14) = 0x03E52239;                                    /* BURST */
    IO32(VI_BASE + 0x18) = 0x0000020D;                                    /* V_SYNC: 525 lines */
    IO32(VI_BASE + 0x1C) = 0x00000C15;                                    /* H_SYNC */
    IO32(VI_BASE + 0x20) = 0x0C150C15;                                    /* LEAP */
    IO32(VI_BASE + 0x24) = 0x006C02EC;                                    /* H_START */
    IO32(VI_BASE + 0x28) = 0x002501FF;                                    /* V_START */
    IO32(VI_BASE + 0x2C) = 0x000E0204;                                    /* V_BURST */
    IO32(VI_BASE + 0x30) = 0x00000200;                                    /* X_SCALE: 320/640 */
    IO32(VI_BASE + 0x34) = 0x00000400;                                    /* Y_SCALE: 1.0 */
}

void lab_wait_vblank(void) {
    /* VI_V_CURRENT counts half-lines; line 2 is the start of vertical blank. */
    while (IO32(VI_BASE + 0x10) == 2) {}
    while (IO32(VI_BASE + 0x10) != 2) {}
}

/* ---- controller ------------------------------------------------------------------- */

#define SI_DRAM_ADDR   0xA4800000
#define SI_PIF_RD64B   0xA4800004
#define SI_PIF_WR64B   0xA4800010
#define SI_STATUS      0xA4800018
#define PIF_RAM        0x1FC007C0

static unsigned char pif_block[64] __attribute__((aligned(8)));

static void si_wait(void) {
    while (IO32(SI_STATUS) & 3) {}
}

LabPad lab_read_pad(void) {
    /* Uncached view of the buffer, so the DMA sees what we write. */
    volatile unsigned char* block = (volatile unsigned char*)((unsigned int)pif_block | 0xA0000000);
    LabPad pad;
    for (int i = 0; i < 64; i++) block[i] = 0;
    block[0] = 0x01;      /* send 1 byte  */
    block[1] = 0x04;      /* receive 4 bytes */
    block[2] = 0x01;      /* command: read buttons */
    block[3] = block[4] = block[5] = block[6] = 0xFF;
    block[7] = 0xFE;      /* end of commands */
    block[63] = 0x01;     /* tell the PIF to run them */

    si_wait();
    IO32(SI_DRAM_ADDR) = (unsigned int)pif_block & 0x1FFFFFFF;
    IO32(SI_PIF_WR64B) = PIF_RAM;
    si_wait();
    IO32(SI_DRAM_ADDR) = (unsigned int)pif_block & 0x1FFFFFFF;
    IO32(SI_PIF_RD64B) = PIF_RAM;
    si_wait();

    pad.buttons = (unsigned short)((block[3] << 8) | block[4]);
    pad.x = (signed char)block[5];
    pad.y = (signed char)block[6];
    return pad;
}

/* ---- C library helpers the compiler may call ----------------------------------------- */

void* memcpy(void* dst, const void* src, unsigned int n) {
    unsigned char* d = dst;
    const unsigned char* s = src;
    while (n--) *d++ = *s++;
    return dst;
}

void* memmove(void* dst, const void* src, unsigned int n) {
    unsigned char* d = dst;
    const unsigned char* s = src;
    if (d < s) {
        while (n--) *d++ = *s++;
    } else {
        while (n--) d[n] = s[n];
    }
    return dst;
}

void* memset(void* dst, int c, unsigned int n) {
    unsigned char* d = dst;
    while (n--) *d++ = (unsigned char)c;
    return dst;
}

/* 64-bit division: MIPS II has no 64-bit divide instruction. */
unsigned long long __udivmoddi4(unsigned long long n, unsigned long long d, unsigned long long* rem) {
    unsigned long long q = 0, r = 0;
    for (int i = 63; i >= 0; i--) {
        r = (r << 1) | ((n >> i) & 1);
        if (r >= d) {
            r -= d;
            q |= 1ull << i;
        }
    }
    if (rem) *rem = r;
    return q;
}

unsigned long long __udivdi3(unsigned long long n, unsigned long long d) { return __udivmoddi4(n, d, 0); }

unsigned long long __umoddi3(unsigned long long n, unsigned long long d) {
    unsigned long long r;
    __udivmoddi4(n, d, &r);
    return r;
}

long long __divdi3(long long n, long long d) {
    int neg = (n < 0) != (d < 0);
    unsigned long long q = __udivmoddi4(n < 0 ? 0 - (unsigned long long)n : (unsigned long long)n,
                                        d < 0 ? 0 - (unsigned long long)d : (unsigned long long)d, 0);
    return neg ? -(long long)q : (long long)q;
}

long long __moddi3(long long n, long long d) {
    unsigned long long r;
    __udivmoddi4(n < 0 ? 0 - (unsigned long long)n : (unsigned long long)n,
                 d < 0 ? 0 - (unsigned long long)d : (unsigned long long)d, &r);
    return n < 0 ? -(long long)r : (long long)r;
}

/* 64-bit integer <-> floating point conversions (no MIPS II instruction for these). */
double __floatundidf(unsigned long long a) {
    return (double)(unsigned int)(a >> 32) * 4294967296.0 + (double)(unsigned int)a;
}

double __floatdidf(long long a) {
    return a < 0 ? -__floatundidf(0 - (unsigned long long)a) : __floatundidf((unsigned long long)a);
}

float __floatdisf(long long a) { return (float)__floatdidf(a); }
float __floatundisf(unsigned long long a) { return (float)__floatundidf(a); }

unsigned long long __fixunsdfdi(double a) {
    if (!(a > 0)) return 0;
    unsigned int hi = (unsigned int)(a / 4294967296.0);
    unsigned int lo = (unsigned int)(a - (double)hi * 4294967296.0);
    return ((unsigned long long)hi << 32) | lo;
}

long long __fixdfdi(double a) {
    return a < 0 ? -(long long)__fixunsdfdi(-a) : (long long)__fixunsdfdi(a);
}

unsigned long long __fixunssfdi(float a) { return __fixunsdfdi(a); }
long long __fixsfdi(float a) { return __fixdfdi(a); }

float sqrtf(float x) { return __builtin_sqrtf(x); }
double sqrt(double x) { return __builtin_sqrt(x); }
