/*
 * hello.c - the smallest useful N64 program: print some text and a few
 * computed values, then stop.  Build it, recompile it, and compare
 * asm/*.s with src/funcs_000.c to see how each line was translated.
 */
#include "n64lab.h"

static int fibonacci(int n) {
    return n < 2 ? n : fibonacci(n - 1) + fibonacci(n - 2);
}

int main(void) {
    lab_puts("Hello from a recompiled N64 program!\n");
    for (int i = 0; i <= 10; i++) {
        lab_printf("fib(%d) = %d\n", i, fibonacci(i));
    }
    return 0;
}
