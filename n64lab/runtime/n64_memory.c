/*
 * n64_memory.c - the N64 memory map and the hardware registers behind it.
 *
 * Physical address map (virtual 0x80000000+ and 0xA0000000+ both map here):
 *
 *   0x00000000  RDRAM (main memory, 4 or 8 MiB)
 *   0x04000000  RSP data memory (DMEM), 0x04001000 instruction memory (IMEM)
 *   0x04040000  RSP registers        0x04100000  RDP registers
 *   0x04300000  MIPS Interface (MI)  0x04400000  Video Interface (VI)
 *   0x04500000  Audio Interface (AI) 0x04600000  Peripheral Interface (PI)
 *   0x04700000  RDRAM Interface (RI) 0x04800000  Serial Interface (SI)
 *   0x10000000  cartridge ROM        0x1FC007C0  PIF RAM (controllers)
 *
 * Only what simple programs need is implemented: PI DMA (load data from the
 * cartridge), SI/PIF (read controller 1), VI registers (to show the
 * framebuffer) and the IS-Viewer debug port (printf output).  The RSP and
 * RDP, which draw 3D graphics and mix audio, are not emulated.
 */
#include <stdlib.h>
#include "n64_internal.h"

uint8_t* n64_rdram;
uint8_t* n64_rom;
uint32_t n64_rom_size;
uint32_t n64_vi_regs[14];

static uint8_t sp_mem[0x2000];      /* DMEM + IMEM */
static uint8_t pif_ram[64];
static uint8_t isviewer_buf[0x1000];
static uint32_t sp_regs[8], dp_regs[8], mi_regs[4], ai_regs[6], pi_regs[13], ri_regs[8], si_regs[7];

#define ISVIEWER_BASE 0x13FF0000u

static const char* const VI_NAMES[14] = {
    "VI_CTRL", "VI_ORIGIN", "VI_WIDTH", "VI_V_INTR", "VI_V_CURRENT", "VI_BURST", "VI_V_SYNC",
    "VI_H_SYNC", "VI_LEAP", "VI_H_START", "VI_V_START", "VI_V_BURST", "VI_X_SCALE", "VI_Y_SCALE",
};

void n64_memory_init(void) {
    n64_rdram = (uint8_t*)calloc(RDRAM_SIZE, 1);
    if (!n64_rdram) {
        n64_log("out of memory");
        exit(1);
    }
}

static uint32_t to_physical(uint32_t vaddr) {
    if (vaddr >= 0x80000000u && vaddr < 0xC0000000u) return vaddr & 0x1FFFFFFFu;
    static int warned;
    if (!warned++) {
        n64_log("address 0x%08X needs the TLB, which is not emulated; treating it as physical", vaddr);
    }
    return vaddr & 0x1FFFFFFFu;
}

/* Memory that is plain bytes: returns a pointer, or NULL for registers. */
static uint8_t* direct(uint32_t phys, uint32_t size, int writing) {
    if (phys + size <= RDRAM_SIZE) return n64_rdram + phys;
    if (phys >= 0x04000000u && phys + size <= 0x04002000u) return sp_mem + (phys - 0x04000000u);
    if (phys >= 0x1FC007C0u && phys + size <= 0x1FC00800u) return pif_ram + (phys - 0x1FC007C0u);
    if (phys >= ISVIEWER_BASE + 0x20 && phys + size <= ISVIEWER_BASE + 0x1000) {
        return isviewer_buf + (phys - ISVIEWER_BASE);
    }
    if (!writing && phys >= 0x10000000u && phys - 0x10000000u + size <= n64_rom_size) {
        return n64_rom + (phys - 0x10000000u);
    }
    return NULL;
}

/* ---- DMA engines ------------------------------------------------------------------ */

static void pi_dma_to_rdram(void) {
    uint32_t dram = pi_regs[0] & 0x7FFFFE, cart = pi_regs[1] & 0x1FFFFFFE;
    uint32_t len = (pi_regs[3] & 0xFFFFFF) + 1;
    if (n64_opts.trace_mmio) n64_log("PI DMA: cart 0x%08X -> RDRAM 0x%06X, %u bytes", cart, dram, len);
    for (uint32_t i = 0; i < len && dram + i < RDRAM_SIZE; i++) {
        uint32_t src = cart - 0x10000000u + i;
        n64_rdram[dram + i] = src < n64_rom_size ? n64_rom[src] : 0;
    }
}

static void sp_dma(int to_rsp) {
    uint32_t mem = sp_regs[0] & 0x1FF8, dram = sp_regs[1] & 0xFFFFF8;
    uint32_t len = ((to_rsp ? sp_regs[2] : sp_regs[3]) & 0xFFF) + 1;
    for (uint32_t i = 0; i < len && mem + i < sizeof sp_mem && dram + i < RDRAM_SIZE; i++) {
        if (to_rsp) sp_mem[mem + i] = n64_rdram[dram + i];
        else n64_rdram[dram + i] = sp_mem[mem + i];
    }
}

/* The PIF chip runs the "joybus" protocol: the CPU writes a list of commands
 * into PIF RAM, and the PIF replaces them with each controller's answer. */
static void pif_process(void) {
    int channel = 0;
    for (int i = 0; i < 63 && channel < 6;) {
        uint8_t tx = pif_ram[i];
        if (tx == 0xFE) break;          /* end of commands */
        if (tx == 0xFF || tx == 0xFD) { /* padding */
            i++;
            continue;
        }
        if (tx == 0) {                  /* skip this channel */
            channel++;
            i++;
            continue;
        }
        if (i + 2 >= 64) break;
        uint8_t rx = pif_ram[i + 1] & 0x3F;
        uint8_t cmd = pif_ram[i + 2];
        uint8_t* reply = &pif_ram[i + 2 + tx];
        if (channel == 0 && reply + rx <= pif_ram + 64) {
            if ((cmd == 0x00 || cmd == 0xFF) && rx >= 3) { /* identify: standard controller */
                reply[0] = 0x05;
                reply[1] = 0x00;
                reply[2] = 0x02;                          /* no Controller Pak inserted */
            } else if (cmd == 0x01 && rx >= 4) {          /* read buttons and stick */
                platform_read_controller(reply);
            } else {
                pif_ram[i + 1] |= 0x80;
            }
        } else {
            pif_ram[i + 1] |= 0x80;                       /* no device on this channel */
        }
        i += 2 + tx + rx;
        channel++;
    }
}

static void si_dma(int to_pif) {
    uint32_t dram = si_regs[0] & 0x7FFFF8;
    if (dram + 64 > RDRAM_SIZE) return;
    if (to_pif) {
        memcpy(pif_ram, n64_rdram + dram, 64);
    } else {
        pif_process();
        memcpy(n64_rdram + dram, pif_ram, 64);
    }
}

/* ---- registers ---------------------------------------------------------------------- */

static uint32_t vi_current_line(void) {
    /* NTSC: 525 half-lines every 1/60 s. Programs poll this to wait for vblank. */
    const uint64_t frame_ns = 16683333;
    return (uint32_t)((n64_time_ns() % frame_ns) * 525 / frame_ns) & ~1u;
}

static uint32_t mmio_read32(uint32_t phys) {
    uint32_t index = (phys & 0xFFFFF) >> 2;
    switch (phys >> 20) {
    case 0x040:
        if (phys == 0x04040010u) return 0x1;   /* SP_STATUS: RSP halted */
        if (phys >= 0x04040000u && phys < 0x04040020u) return sp_regs[(phys - 0x04040000u) >> 2];
        if (phys == 0x04080000u) return 0;     /* SP_PC */
        break;
    case 0x041: return index == 3 ? 0 : (index < 8 ? dp_regs[index] : 0);
    case 0x043:
        if (index == 1) return 0x02020102;     /* MI_VERSION */
        return index < 4 ? mi_regs[index] : 0;
    case 0x044:
        if (index == 4) return vi_current_line();
        return index < 14 ? n64_vi_regs[index] : 0;
    case 0x045:
        if (index == 1) return 0;              /* AI_LEN: buffer empty */
        if (index == 3) return 0;              /* AI_STATUS: not full, not busy */
        return index < 6 ? ai_regs[index] : 0;
    case 0x046:
        if (index == 4) return 0;              /* PI_STATUS: DMA idle */
        return index < 13 ? pi_regs[index] : 0;
    case 0x047: return index < 8 ? ri_regs[index] : 0;
    case 0x048:
        if (index == 6) return 0;              /* SI_STATUS: idle */
        return index < 7 ? si_regs[index] : 0;
    default:
        break;
    }
    static int warned;
    if (warned++ < 16) n64_log("read from unmapped address 0x%08X (returning 0)", phys);
    return 0;
}

static void isviewer_write(uint32_t phys, uint32_t value) {
    if (phys == ISVIEWER_BASE + 0x14) {        /* length register: print the buffer */
        uint32_t len = value < sizeof isviewer_buf - 0x20 ? value : sizeof isviewer_buf - 0x20;
        fwrite(isviewer_buf + 0x20, 1, len, stdout);
        fflush(stdout);
    }
}

static void mmio_write32(uint32_t phys, uint32_t value) {
    uint32_t index = (phys & 0xFFFFF) >> 2;
    if (phys >= ISVIEWER_BASE && phys < ISVIEWER_BASE + 0x20) {
        isviewer_write(phys, value);
        return;
    }
    switch (phys >> 20) {
    case 0x040:
        if (phys >= 0x04040000u && phys < 0x04040020u) {
            index = (phys - 0x04040000u) >> 2;
            if (index == 4) {                  /* SP_STATUS */
                if (value & 1) {
                    static int warned;
                    if (!warned++) n64_log("RSP task started: the RSP is not emulated, so "
                                           "3D graphics and audio will not work");
                }
                return;
            }
            sp_regs[index] = value;
            if (index == 2) sp_dma(1);
            if (index == 3) sp_dma(0);
        }
        return;
    case 0x041: if (index < 8) dp_regs[index] = value; return;
    case 0x043: if (index < 4 && index != 1) mi_regs[index] = value; return;
    case 0x044:
        if (index < 14) {
            if (n64_opts.trace_mmio) n64_log("%s = 0x%08X", VI_NAMES[index], value);
            if (index != 4) n64_vi_regs[index] = value;
        }
        return;
    case 0x045: if (index < 6) ai_regs[index] = value; return;
    case 0x046:
        if (index < 13) {
            pi_regs[index] = value;
            if (index == 3) pi_dma_to_rdram();
        }
        return;
    case 0x047: if (index < 8) ri_regs[index] = value; return;
    case 0x048:
        if (index < 7) {
            si_regs[index] = value;
            if (index == 1) si_dma(0);         /* SI_PIF_AD_RD64B: PIF -> RDRAM */
            if (index == 4) si_dma(1);         /* SI_PIF_AD_WR64B: RDRAM -> PIF */
        }
        return;
    default:
        break;
    }
    static int warned;
    if (warned++ < 16) n64_log("write of 0x%08X to unmapped address 0x%08X ignored", value, phys);
}

/* ---- public accessors -------------------------------------------------------------- */

uint8_t mem_read8(uint32_t addr) {
    uint32_t p = to_physical(addr);
    uint8_t* d = direct(p, 1, 0);
    if (d) return d[0];
    return (uint8_t)(mmio_read32(p & ~3u) >> (24 - 8 * (p & 3)));
}

uint16_t mem_read16(uint32_t addr) {
    uint32_t p = to_physical(addr);
    uint8_t* d = direct(p, 2, 0);
    if (d) return (uint16_t)((d[0] << 8) | d[1]);
    return (uint16_t)(mmio_read32(p & ~3u) >> (16 - 8 * (p & 2)));
}

uint32_t mem_read32(uint32_t addr) {
    uint32_t p = to_physical(addr);
    uint8_t* d = direct(p, 4, 0);
    if (d) return ((uint32_t)d[0] << 24) | ((uint32_t)d[1] << 16) | ((uint32_t)d[2] << 8) | d[3];
    return mmio_read32(p);
}

uint64_t mem_read64(uint32_t addr) {
    return ((uint64_t)mem_read32(addr) << 32) | mem_read32(addr + 4);
}

void mem_write8(uint32_t addr, uint8_t value) {
    uint32_t p = to_physical(addr);
    uint8_t* d = direct(p, 1, 1);
    if (d) d[0] = value;
    else mmio_write32(p & ~3u, (uint32_t)value << (24 - 8 * (p & 3)));
}

void mem_write16(uint32_t addr, uint16_t value) {
    uint32_t p = to_physical(addr);
    uint8_t* d = direct(p, 2, 1);
    if (d) {
        d[0] = (uint8_t)(value >> 8);
        d[1] = (uint8_t)value;
    } else {
        mmio_write32(p & ~3u, (uint32_t)value << (16 - 8 * (p & 2)));
    }
}

void mem_write32(uint32_t addr, uint32_t value) {
    uint32_t p = to_physical(addr);
    uint8_t* d = direct(p, 4, 1);
    if (d) {
        d[0] = (uint8_t)(value >> 24);
        d[1] = (uint8_t)(value >> 16);
        d[2] = (uint8_t)(value >> 8);
        d[3] = (uint8_t)value;
    } else {
        mmio_write32(p, value);
    }
}

void mem_write64(uint32_t addr, uint64_t value) {
    mem_write32(addr, (uint32_t)(value >> 32));
    mem_write32(addr + 4, (uint32_t)value);
}

/* ---- video output ------------------------------------------------------------------ */

int n64_framebuffer(uint32_t* out, int max_pixels, int* width, int* height) {
    uint32_t ctrl = n64_vi_regs[0], origin = n64_vi_regs[1] & 0xFFFFFF, w = n64_vi_regs[2] & 0xFFF;
    int type = ctrl & 3;            /* 2 = 16-bit RGBA5551, 3 = 32-bit RGBA8888 */
    if (type < 2 || w == 0 || w > 1024) return 0;
    uint32_t v_start = n64_vi_regs[10], y_scale = n64_vi_regs[13] & 0xFFF;
    int lines = (int)(((v_start & 0x3FF) - ((v_start >> 16) & 0x3FF)) / 2);
    int h = (lines > 0 && y_scale) ? (int)((uint32_t)lines * y_scale / 1024) : (w > 320 ? 480 : 240);
    if (h <= 0 || h > 576) h = w > 320 ? 480 : 240;
    if (h >= 224 && h < 240) h = 240; /* NTSC timings show ~237 lines; programs draw 240 */
    if (h >= 464 && h < 480) h = 480;
    if ((int)w * h > max_pixels) return 0;
    int bpp = type == 2 ? 2 : 4;
    for (int y = 0; y < h; y++) {
        for (uint32_t x = 0; x < w; x++) {
            uint32_t a = origin + ((uint32_t)y * w + x) * bpp, rgb = 0;
            if (a + bpp <= RDRAM_SIZE) {
                const uint8_t* px = n64_rdram + a;
                if (bpp == 2) {
                    uint16_t c = (uint16_t)((px[0] << 8) | px[1]);
                    uint32_t r = (c >> 11) & 31, g = (c >> 6) & 31, b = (c >> 1) & 31;
                    rgb = ((r << 3 | r >> 2) << 16) | ((g << 3 | g >> 2) << 8) | (b << 3 | b >> 2);
                } else {
                    rgb = ((uint32_t)px[0] << 16) | ((uint32_t)px[1] << 8) | px[2];
                }
            }
            out[y * w + x] = rgb;
        }
    }
    *width = (int)w;
    *height = h;
    return 1;
}

int n64_write_screenshot(const char* path) {
    static uint32_t pixels[1024 * 576];
    int w, h;
    if (!n64_framebuffer(pixels, 1024 * 576, &w, &h)) {
        n64_log("no screenshot: the program never set up a framebuffer");
        return 0;
    }
    FILE* f = fopen(path, "wb");
    if (!f) {
        n64_log("cannot write %s", path);
        return 0;
    }
    fprintf(f, "P6\n%d %d\n255\n", w, h);
    for (int i = 0; i < w * h; i++) {
        uint8_t rgb[3] = {(uint8_t)(pixels[i] >> 16), (uint8_t)(pixels[i] >> 8), (uint8_t)pixels[i]};
        fwrite(rgb, 1, 3, f);
    }
    fclose(f);
    n64_log("wrote %dx%d screenshot to %s", w, h, path);
    return 1;
}
