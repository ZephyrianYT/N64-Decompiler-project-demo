/* Control flow: switches (jump tables), function pointers, recursion, loops. */
#include "n64lab.h"

static int dense_switch(int x) {
    switch (x) {
    case 0: return x * 3 + 1;
    case 1: return dense_switch(x - 1) + 10;
    case 2: lab_puts("two "); return 22;
    case 3: return x << 4;
    case 4: return -x;
    case 5: lab_puts("five "); /* fall through */
    case 6: return 66;
    case 7: return x ^ 0x55;
    case 8: return dense_switch(x - 2) * 2;
    default: return -1;
    }
}

static int sparse_switch(int x) {
    switch (x) {
    case 10: return 1;
    case 1000: return 2;
    case -5: return 3;
    case 77777: return 4;
    default: return 0;
    }
}

typedef int (*BinOp)(int, int);
static int add(int a, int b) { return a + b; }
static int sub(int a, int b) { return a - b; }
static int mul(int a, int b) { return a * b; }
static int maxi(int a, int b) { return a > b ? a : b; }
static BinOp ops[] = {add, sub, mul, maxi};

static int ackermann(int m, int n) {
    if (m == 0) return n + 1;
    if (n == 0) return ackermann(m - 1, 1);
    return ackermann(m - 1, ackermann(m, n - 1));
}

static int collatz_steps(unsigned int n) {
    int steps = 0;
    while (n != 1) {
        n = (n & 1) ? 3 * n + 1 : n / 2;
        steps++;
    }
    return steps;
}

__attribute__((noinline)) static int apply(BinOp op, int a, int b) { return op(a, b); }

int main(void) {
    for (int i = -1; i < 10; i++) lab_printf("dense(%d)=%d\n", i, dense_switch(i));
    int keys[] = {10, 1000, -5, 77777, 3};
    for (int i = 0; i < 5; i++) lab_printf("sparse(%d)=%d\n", keys[i], sparse_switch(keys[i]));
    for (int i = 0; i < 4; i++) lab_printf("op%d(9,4)=%d\n", i, apply(ops[i], 9, 4));
    lab_printf("ackermann(2,3)=%d\n", ackermann(2, 3));
    int best = 0, best_n = 0;
    for (unsigned int n = 1; n < 3000; n++) {
        int s = collatz_steps(n);
        if (s > best) {
            best = s;
            best_n = (int)n;
        }
    }
    lab_printf("longest collatz below 3000: %d (%d steps)\n", best_n, best);
    int primes = 0;
    for (int n = 2; n < 2000; n++) {
        int prime = 1;
        for (int d = 2; d * d <= n; d++) {
            if (n % d == 0) {
                prime = 0;
                break;
            }
        }
        primes += prime;
    }
    lab_printf("primes below 2000: %d\n", primes);
    return 0;
}
