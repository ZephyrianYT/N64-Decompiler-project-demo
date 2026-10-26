/* Runs the hand-written assembly tests in mips3.S and prints their results. */
#include "n64lab.h"

void mips3_tests(unsigned int* out);

int main(void) {
    unsigned int out[34];
    for (int i = 0; i < 34; i++) out[i] = 0xDEADBEEF;
    mips3_tests(out);
    for (int i = 0; i < 34; i++) lab_printf("%02d: %08x\n", i, out[i]);
    return 0;
}
