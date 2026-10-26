/* platform_posix.c - Linux/macOS: headless only (console output + screenshots). */
#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#include <pthread.h>
#include <signal.h>
#include <stdlib.h>
#include <time.h>
#include "n64_internal.h"

static void (*game_fn)(void);
static volatile int finished;
static int exit_code;
static volatile sig_atomic_t interrupted;

static void on_interrupt(int sig) {
    (void)sig;
    interrupted = 1;
}

uint64_t platform_time_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

int platform_claim_once(volatile long* flag) { return __sync_lock_test_and_set(flag, 1) == 0; }

void platform_read_controller(uint8_t out[4]) { memset(out, 0, 4); }

void platform_exit_game_thread(int code) {
    exit_code = code;
    finished = 1;
    pthread_exit(NULL);
}

static void* thread_main(void* unused) {
    (void)unused;
    game_fn();
    return NULL;
}

int platform_run(void (*game_thread)(void)) {
    pthread_t thread;
    pthread_attr_t attr;
    game_fn = game_thread;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, 64u << 20); /* recompiled calls nest on the native stack */
    if (pthread_create(&thread, &attr, thread_main, NULL)) {
        n64_log("cannot start the game thread");
        return 1;
    }
    signal(SIGINT, on_interrupt);
    while (!finished) {
        struct timespec nap = {0, 5000000};
        nanosleep(&nap, NULL);
        if (interrupted) {
            n64_log("interrupted");
            n64_print_call_stack();
            fflush(stdout);
            exit(130);
        }
        if (n64_opts.seconds > 0 && n64_time_ns() > (uint64_t)(n64_opts.seconds * 1e9)) {
            n64_final_screenshot();
            n64_log("time limit of %g s reached", n64_opts.seconds);
            n64_print_call_stack();
            fflush(stdout);
            exit(0);
        }
    }
    pthread_join(thread, NULL);
    return exit_code;
}
#endif
