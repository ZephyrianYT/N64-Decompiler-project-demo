/*
 * n64_main.c - program entry: load the ROM, do what the console's boot code
 * (IPL3) would have done, then run the recompiled entry point.
 */
#include <stdarg.h>
#include <stdlib.h>
#include "n64_internal.h"

N64Options n64_opts;
CPUState n64_cpu;
static uint64_t start_ns;

void n64_log(const char* fmt, ...) {
    va_list args;
    fflush(stdout);
    fputs("[n64] ", stderr);
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    va_end(args);
    fputc('\n', stderr);
    fflush(stderr);
}

uint64_t n64_time_ns(void) { return platform_time_ns() - start_ns; }

void n64_halt(int exit_code, const char* reason) {
    if (n64_opts.screenshot_path) n64_write_screenshot(n64_opts.screenshot_path);
    n64_log("stopped (%s), exit code %d", reason, exit_code);
    fflush(stdout);
    platform_exit_game_thread(exit_code);
}

static uint8_t* read_file(const char* path, uint32_t* size) {
    FILE* f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t* data = len > 0 ? (uint8_t*)malloc((size_t)len) : NULL;
    if (data && fread(data, 1, (size_t)len, f) != (size_t)len) {
        free(data);
        data = NULL;
    }
    fclose(f);
    *size = (uint32_t)len;
    return data;
}

/* ROM dumps come in three byte orders; convert to big-endian (.z64). */
static int normalize_rom(uint8_t* rom, uint32_t size) {
    if (size < 0x1000) return 0;
    uint8_t first = rom[0];
    if (first == 0x80) return rom[1] == 0x37;
    if (first != 0x37 && first != 0x40) return 0;
    for (uint32_t i = 0; i + 3 < size; i += 4) {
        uint8_t a = rom[i], b = rom[i + 1], c = rom[i + 2], d = rom[i + 3];
        if (first == 0x37) { rom[i] = b; rom[i + 1] = a; rom[i + 2] = d; rom[i + 3] = c; } /* .v64 */
        else { rom[i] = d; rom[i + 1] = c; rom[i + 2] = b; rom[i + 3] = a; }               /* .n64 */
    }
    return 1;
}

static uint32_t be32(const uint8_t* p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static void boot(void) {
    /* IPL3 copies the first 1 MiB of the game into RDRAM at the entry point. */
    uint32_t dest = n64_game.entry & 0x1FFFFFFF;
    for (uint32_t i = 0; i < n64_game.boot_size; i++) {
        uint32_t src = n64_game.boot_rom_start + i;
        if (dest + i < RDRAM_SIZE) n64_rdram[dest + i] = src < n64_rom_size ? n64_rom[src] : 0;
    }
    /* ...and leaves some information for libultra's osInitialize. */
    mem_write32(0x80000300, 1);              /* osTvType: NTSC */
    mem_write32(0x80000304, 0);              /* osRomType: cartridge */
    mem_write32(0x80000308, 0xB0000000);     /* osRomBase */
    mem_write32(0x8000030C, 0);              /* osResetType: cold boot */
    mem_write32(0x80000318, RDRAM_SIZE);     /* osMemSize */

    memset(&n64_cpu, 0, sizeof n64_cpu);
    n64_cpu.sp = S32(0xA4001FF0);            /* IPL3 leaves the stack in RSP memory */
    n64_cpu.t3 = S32(0xA4000040);
    n64_cpu.cop0[12] = 0x34000000;           /* Status: COP1 usable, FR=0 */
    n64_cpu.fcr31 = 0x01000800;
}

static void game_thread(void) {
    n64_game_entry(&n64_cpu);
    n64_log("the entry function returned (real games never do this)");
    n64_halt(0, "entry returned");
}

static void usage(const char* exe) {
    fprintf(stderr,
            "usage: %s [rom.z64] [options]\n"
            "  --headless          no window (for tests and scripting)\n"
            "  --seconds N         stop after N seconds\n"
            "  --screenshot F.ppm  save the last frame when the program stops\n"
            "  --trace-mmio        log hardware register writes (VI, PI DMA)\n"
            "  --scale N           window scale (default 2)\n"
            "Without a ROM path, baserom.z64 in the current directory is used.\n", exe);
}

int main(int argc, char** argv) {
    n64_opts.rom_path = "baserom.z64";
    n64_opts.scale = 2;
    for (int i = 1; i < argc; i++) {
        const char* a = argv[i];
        if (!strcmp(a, "--headless")) n64_opts.headless = 1;
        else if (!strcmp(a, "--trace-mmio")) n64_opts.trace_mmio = 1;
        else if (!strcmp(a, "--seconds") && i + 1 < argc) n64_opts.seconds = atof(argv[++i]);
        else if (!strcmp(a, "--screenshot") && i + 1 < argc) n64_opts.screenshot_path = argv[++i];
        else if (!strcmp(a, "--scale") && i + 1 < argc) n64_opts.scale = atoi(argv[++i]);
        else if (!strcmp(a, "--help") || !strcmp(a, "-h")) { usage(argv[0]); return 0; }
        else if (a[0] == '-') { usage(argv[0]); return 2; }
        else n64_opts.rom_path = a;
    }
    if (n64_opts.scale < 1) n64_opts.scale = 1;

    n64_rom = read_file(n64_opts.rom_path, &n64_rom_size);
    if (!n64_rom) {
        n64_log("cannot open ROM '%s'", n64_opts.rom_path);
        usage(argv[0]);
        return 2;
    }
    if (!normalize_rom(n64_rom, n64_rom_size)) {
        n64_log("'%s' is not an N64 ROM", n64_opts.rom_path);
        return 2;
    }
    if (be32(n64_rom + 0x10) != n64_game.header_crc1 || be32(n64_rom + 0x14) != n64_game.header_crc2) {
        n64_log("warning: this ROM's checksum does not match the one this program was "
                "recompiled from (%s). Expect problems.", n64_game.title);
    }

    n64_log("%s [%s], entry 0x%08X, %u recompiled functions", n64_game.title,
            n64_game.game_code, n64_game.entry, (unsigned)n64_function_count);
    start_ns = platform_time_ns();
    n64_memory_init();
    boot();
    return platform_run(game_thread);
}
