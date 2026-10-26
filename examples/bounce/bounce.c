/*
 * bounce.c - draw straight into the framebuffer, like the earliest N64
 * homebrew did before using the RDP.  A square bounces around a gradient
 * background; hold A (the X key in the Windows build) to steer it with the
 * stick (arrow keys).
 *
 * Things to look for in the recompiled C:
 *   - lab_video_init() is a list of SW stores to 0xA44000xx: the VI registers.
 *   - lab_wait_vblank() is a loop that keeps reading VI_V_CURRENT.
 *   - lab_read_pad() talks to the PIF chip through the SI DMA registers.
 */
#include "n64lab.h"

#define WIDTH 320
#define HEIGHT 240
#define SIZE 24

static unsigned short framebuffer[WIDTH * HEIGHT] __attribute__((aligned(64)));

static void draw_background(int frame) {
    for (int y = 0; y < HEIGHT; y++) {
        for (int x = 0; x < WIDTH; x++) {
            int r = (x * 255) / WIDTH;
            int g = (y * 255) / HEIGHT;
            int b = (frame * 2) & 255;
            framebuffer[y * WIDTH + x] = RGBA16(r, g, b);
        }
    }
}

static void draw_square(int left, int top, unsigned short color) {
    for (int y = top; y < top + SIZE; y++) {
        for (int x = left; x < left + SIZE; x++) {
            framebuffer[y * WIDTH + x] = color;
        }
    }
}

int main(void) {
    int x = 40, y = 60, dx = 3, dy = 2;
    lab_video_init(framebuffer, 16);
    lab_puts("bounce: hold A (X key) and use the stick (arrow keys) to steer\n");
    for (int frame = 0;; frame++) {
        LabPad pad = lab_read_pad();
        if (pad.buttons & LAB_BTN_A) {
            dx = pad.x / 16;
            dy = -pad.y / 16;
        }
        x += dx;
        y += dy;
        if (x < 0) { x = 0; dx = -dx; }
        if (y < 0) { y = 0; dy = -dy; }
        if (x > WIDTH - SIZE) { x = WIDTH - SIZE; dx = -dx; }
        if (y > HEIGHT - SIZE) { y = HEIGHT - SIZE; dy = -dy; }
        draw_background(frame);
        draw_square(x, y, (pad.buttons & LAB_BTN_A) ? RGBA16(255, 255, 0) : RGBA16(255, 255, 255));
        lab_wait_vblank();
    }
}
