/* Memory: globals, bss, struct copies, byte/half access, unaligned fields. */
#include "n64lab.h"

typedef struct {
    char tag;
    int value;
    short half;
    long long wide;
} __attribute__((packed)) Packed;

typedef struct {
    int x, y, z;
    char name[13];
} Thing;

static Packed packed_items[3] = {{'a', 0x11223344, -2, 0x0102030405060708LL}, {'b', -1, 300, -5}, {'c', 7, 7, 7}};
static Thing things[4];
static int bss_counter;

/* The N64 is big-endian and a PC is little-endian; these keep the printed
 * results the same on both so the outputs can be compared. */
#ifdef __mips__
#define FROM_BE32(v) (v)
#define BE(i) (i)
#else
#define FROM_BE32(v) __builtin_bswap32(v)
#define BE(i) (3 - (i))
#endif
static const char message[] = "big-endian bytes";

static void make_thing(Thing* t, int n) {
    Thing tmp = {n, n * n, -n, "thing #"};
    tmp.name[7] = (char)('0' + n);
    tmp.name[8] = 0;
    *t = tmp;  /* struct copy */
}

int main(void) {
    for (int i = 0; i < 4; i++) {
        make_thing(&things[i], i);
        bss_counter += things[i].y;
    }
    for (int i = 0; i < 4; i++) {
        lab_printf("%s: %d %d %d\n", things[i].name, things[i].x, things[i].y, things[i].z);
    }
    lab_printf("bss_counter=%d\n", bss_counter);

    for (int i = 0; i < 3; i++) {
        volatile Packed* p = &packed_items[i];
        p->value += i;
        p->wide = p->wide * 3 + 1;
        lab_printf("packed %c %08x %d %08x%08x\n", p->tag, (unsigned int)p->value, p->half,
                   (unsigned int)((unsigned long long)p->wide >> 32), (unsigned int)p->wide);
    }

    const unsigned char* bytes = (const unsigned char*)message;
    unsigned int word = ((unsigned int)bytes[0] << 24) | (bytes[1] << 16) | (bytes[2] << 8) | bytes[3];
    lab_printf("first word of message: %08x\n", word);
    volatile unsigned int big = 0xA1B2C3D4;
    volatile unsigned char* b = (volatile unsigned char*)&big;
    volatile unsigned short* s = (volatile unsigned short*)&big;
    lab_printf("byte order: %02x %02x %04x\n", b[BE(0)], b[BE(3)], s[BE(2) / 2]);

    unsigned char buffer[64];
    for (int i = 0; i < 64; i++) buffer[i] = (unsigned char)(i * 7);
    unsigned int sum = 0;
    for (int i = 0; i < 61; i++) {
        unsigned int v;
        memcpy(&v, buffer + i, 4);  /* unaligned reads (lwl/lwr on MIPS) */
        sum = sum * 33 + FROM_BE32(v);
    }
    lab_printf("unaligned sum %08x\n", sum);
    return 0;
}
