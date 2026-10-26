/* State shared between the runtime's own source files (not used by generated code). */
#ifndef N64_INTERNAL_H
#define N64_INTERNAL_H

#include <stdio.h>
#include "n64_runtime.h"

#define RDRAM_SIZE 0x800000u   /* 8 MiB: a console with the Expansion Pak */

typedef struct N64Options {
    const char* rom_path;
    const char* screenshot_path; /* write the last frame here on exit (.ppm) */
    double seconds;              /* stop after this long; 0 = run until the program ends */
    int headless;
    int trace_mmio;
    int scale;
} N64Options;

extern N64Options n64_opts;
extern uint8_t* n64_rdram;
extern uint8_t* n64_rom;
extern uint32_t n64_rom_size;
extern uint32_t n64_vi_regs[14];
extern CPUState n64_cpu;

void n64_log(const char* fmt, ...);
void n64_memory_init(void);
uint64_t n64_time_ns(void);

/* Framebuffer as described by the VI registers, converted to 0x00RRGGBB.
 * Returns 0 when the program has not set up video yet. */
int n64_framebuffer(uint32_t* out, int max_pixels, int* width, int* height);
int n64_write_screenshot(const char* path);
/* Save --screenshot once at exit; safe to call from the game and main threads at the same time. */
void n64_final_screenshot(void);

/* Ends the program from inside recompiled code. */
void n64_halt(int exit_code, const char* reason);

/* Provided by platform_*.c */
int platform_run(void (*game_thread)(void));
void platform_exit_game_thread(int exit_code);
void platform_read_controller(uint8_t out[4]);
uint64_t platform_time_ns(void);
int platform_claim_once(volatile long* flag);  /* atomically: returns 1 for the first caller only */

#endif
