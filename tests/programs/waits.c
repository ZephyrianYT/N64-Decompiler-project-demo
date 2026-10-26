/* Waits for hardware that n64lab never makes ready: a hang, on purpose.
 * Used to test --debug-calls (find where it hangs) and stub return
 * values (skip the wait by making device_ready() return 1). */
#include "n64lab.h"

#define PI_STATUS (*(volatile unsigned int*)0xA4600010)

__attribute__((noinline)) int device_ready(void) { return PI_STATUS == 0x1234; }

__attribute__((noinline)) void wait_for_device(void) {
    while (!device_ready()) {}
}

int main(void) {
    lab_puts("waiting for the device\n");
    wait_for_device();
    lab_puts("device ready\n");
    return 0;
}
