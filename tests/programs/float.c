/* Floating point: single and double precision, conversions, compares. */
#include "n64lab.h"

volatile float vf[] = {1.5f, -2.25f, 3.0e10f, 0.1f, -0.0f, 1e-30f};
volatile double vd[] = {2.5, -1.0e100, 0.3, 123456.789, -7.5};

/* Print floats as fixed-point integers, avoiding undefined out-of-range casts. */
static int fix(double v) {
    double s = v * 1000.0;
    if (s != s) return -999;
    if (s > 2e9) return 2000000000;
    if (s < -2e9) return -2000000000;
    return (int)s;
}

static float poly(float x) { return ((0.5f * x - 1.25f) * x + 3.0f) * x - 0.75f; }

static double newton_sqrt(double v) {
    double x = v > 1 ? v : 1;
    for (int i = 0; i < 30; i++) x = 0.5 * (x + v / x);
    return x;
}

int main(void) {
    for (int i = 0; i < 6; i++) {
        float a = vf[i], b = vf[(i + 1) % 6];
        lab_printf("f%d: %d %d %d %d %d\n", i, fix(a + b), fix(a - b), fix(a * b),
                   b != 0 ? fix(a / b) : 0, (a < b) + 2 * (a == b) + 4 * (a > b));
    }
    for (int i = 0; i < 5; i++) {
        double a = vd[i], b = vd[(i + 2) % 5];
        double q = a / b;
        lab_printf("d%d: %d %d %d\n", i, fix(q > 1e6 || q < -1e6 ? 0 : q), (a <= b), fix((float)(a * 0.001)));
    }
    int conv[] = {(int)2.7f, (int)-2.7f, (int)2.5, (int)-0.5, (int)(unsigned int)3.99f};
    lab_printf("trunc: %d %d %d %d %d\n", conv[0], conv[1], conv[2], conv[3], conv[4]);
    for (int i = -3; i <= 3; i++) lab_printf("poly(%d)=%d\n", i, fix(poly((float)i * 0.5f)));
    lab_printf("sqrt(2)=%d sqrt(1e6)=%d\n", fix(newton_sqrt(2.0)), fix(newton_sqrt(1e6)));
    lab_printf("sqrtf builtin=%d\n", fix(__builtin_sqrtf(vf[2])) / 1000);
    float acc = 0;
    for (int i = 1; i <= 1000; i++) acc += 1.0f / (float)i;
    lab_printf("harmonic(1000) as float=%d\n", fix(acc));
    double dacc = 0;
    for (int i = 1; i <= 1000; i++) dacc += 1.0 / ((double)i * i);
    lab_printf("basel(1000)=%d\n", fix(dacc * 1000));
    unsigned int big = 4000000000u;
    lab_printf("uint->float->uint %u\n", (unsigned int)(float)big);
    long long ll = -123456789012LL;
    lab_printf("ll->double %d\n", fix((double)ll / 1e9));
    volatile float nan = vf[4] / vf[4];
    lab_printf("nan compares: %d %d %d\n", nan == nan, nan < 1.0f, nan != nan);
    return 0;
}
