/* Integer arithmetic: the recompiled output must match a native build exactly. */
#include "n64lab.h"

volatile int vi[] = {7, -7, 3, -3, 0x7FFFFFFF, (int)0x80000000, 0, 1, 100000};
volatile unsigned int vu[] = {7, 3, 0xFFFFFFFFu, 0x80000000u, 12345678u};
volatile long long vl[] = {123456789012345LL, -98765432109LL, 7, -3, 0x7FFFFFFFFFFFFFFFLL};
volatile signed char vc[] = {-1, 127, -128, 5};
volatile short vs[] = {-1, 32767, -32768, 1234};

static unsigned int hash(unsigned int h, unsigned int v) { return (h ^ v) * 16777619u; }

int main(void) {
    unsigned int h = 2166136261u;
    for (int i = 0; i < 9; i++) {
        for (int j = 0; j < 9; j++) {
            int a = vi[i], b = vi[j];
            h = hash(h, (unsigned int)(a + b));
            h = hash(h, (unsigned int)(a - b));
            h = hash(h, (unsigned int)a * (unsigned int)b);
            if (b != 0 && !(a == (int)0x80000000 && b == -1)) {
                h = hash(h, (unsigned int)(a / b));
                h = hash(h, (unsigned int)(a % b));
            }
            h = hash(h, (unsigned int)(a < b) | (unsigned int)(a <= b) << 1);
            h = hash(h, (unsigned int)(a >> (j & 31)));
            h = hash(h, (unsigned int)a << (i & 31));
        }
    }
    lab_printf("signed hash   %08x\n", h);

    for (int i = 0; i < 5; i++) {
        for (int j = 0; j < 5; j++) {
            unsigned int a = vu[i], b = vu[j];
            h = hash(h, a / b);
            h = hash(h, a % b);
            h = hash(h, a >> (j * 7 & 31));
            h = hash(h, (a < b) + (a > b) * 2);
            unsigned long long wide = (unsigned long long)a * b;
            h = hash(h, (unsigned int)(wide >> 32));
        }
    }
    lab_printf("unsigned hash %08x\n", h);

    for (int i = 0; i < 5; i++) {
        for (int j = 0; j < 5; j++) {
            long long a = vl[i], b = vl[j];
            long long r[] = {a + b, a - b, (long long)((unsigned long long)a * (unsigned long long)b),
                             b ? a / b : 0, b ? a % b : 0, a >> (j * 9), (long long)((unsigned long long)a << (i * 11)),
                             a < b, (long long)((unsigned long long)a >> (i + j))};
            for (int k = 0; k < 9; k++) {
                h = hash(h, (unsigned int)r[k]);
                h = hash(h, (unsigned int)((unsigned long long)r[k] >> 32));
            }
        }
    }
    lab_printf("64-bit hash   %08x\n", h);

    int sum = 0;
    for (int i = 0; i < 4; i++) sum = sum * 31 + vc[i] + vs[i];
    lab_printf("char/short    %d\n", sum);
    lab_printf("negatives     %d %d %d %d\n", -7 / 2, -7 % 2, vi[1] / vi[2], vi[1] % vi[2]);
    lab_printf("bits          %08x %08x %08x\n", vu[2] ^ vu[4], ~vu[4], vu[4] & 0x00FF00FF);
    return 0;
}
