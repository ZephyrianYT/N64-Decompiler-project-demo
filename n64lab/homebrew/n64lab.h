/*
 * n64lab.h - a tiny "SDK" for bare-metal N64 test programs.
 *
 * Programs built with this header talk straight to the hardware registers;
 * there is no operating system.  When compiled for a PC (no __mips__), the
 * print functions map to printf so the same program can be run natively and
 * its output compared with the recompiled version.
 */
#ifndef N64LAB_H
#define N64LAB_H

#ifdef __mips__

#include <stdarg.h>

/* Uncached access to a hardware register. */
#define IO32(addr) (*(volatile unsigned int*)(addr))

void lab_puts(const char* s);
void lab_printf(const char* fmt, ...);
void* memcpy(void* dst, const void* src, unsigned int n);
void* memmove(void* dst, const void* src, unsigned int n);
void* memset(void* dst, int c, unsigned int n);
static inline void lab_exit(void) { __asm__ volatile("break 0"); }

/* Video: point the VI at a 320x240 framebuffer (16-bit RGBA5551 or 32-bit). */
void lab_video_init(void* framebuffer, int bits_per_pixel);
void lab_wait_vblank(void);
#define RGBA16(r, g, b) ((unsigned short)((((r) >> 3) << 11) | (((g) >> 3) << 6) | (((b) >> 3) << 1) | 1))

/* Controller 1, read through the PIF chip. */
typedef struct {
    unsigned short buttons;   /* see LAB_BTN_* */
    signed char x, y;         /* analog stick, roughly -80..80 */
} LabPad;
LabPad lab_read_pad(void);

#define LAB_BTN_A      0x8000
#define LAB_BTN_B      0x4000
#define LAB_BTN_Z      0x2000
#define LAB_BTN_START  0x1000
#define LAB_BTN_UP     0x0800
#define LAB_BTN_DOWN   0x0400
#define LAB_BTN_LEFT   0x0200
#define LAB_BTN_RIGHT  0x0100
#define LAB_BTN_L      0x0020
#define LAB_BTN_R      0x0010

#else /* native build, for comparing output */

#include <stdio.h>
#include <string.h>
#define lab_puts(s) fputs((s), stdout)
#define lab_printf printf
#define lab_exit() ((void)0)

#endif
#endif
