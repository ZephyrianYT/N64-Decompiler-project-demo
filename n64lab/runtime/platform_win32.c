/*
 * platform_win32.c - Windows: a window that shows the N64 framebuffer, and
 * keyboard input mapped to controller 1.
 *
 * The recompiled program runs on its own thread, exactly like the CPU runs
 * independently of the TV on a real console.  The window thread just reads
 * the framebuffer the VI registers point at, 60 times a second.
 *
 * Keys:  arrows = stick   X = A   C = B   Z = Z   Enter = Start
 *        Q / E = L / R    I J K L = C buttons    T F G H = D-pad
 */
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdlib.h>
#include "n64_internal.h"

#define MAX_PIXELS (1024 * 576)

static void (*game_fn)(void);
static volatile LONG finished;
static int exit_code;
static HWND window;
static uint32_t pixels[MAX_PIXELS];

uint64_t platform_time_ns(void) {
    static LARGE_INTEGER freq;
    LARGE_INTEGER now;
    if (!freq.QuadPart) QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&now);
    return (uint64_t)(now.QuadPart / freq.QuadPart) * 1000000000ull +
           (uint64_t)(now.QuadPart % freq.QuadPart) * 1000000000ull / (uint64_t)freq.QuadPart;
}

int platform_claim_once(volatile long* flag) { return InterlockedExchange(flag, 1) == 0; }

static int key(int vk) { return (GetAsyncKeyState(vk) & 0x8000) != 0; }

void platform_read_controller(uint8_t out[4]) {
    memset(out, 0, 4);
    if (!window || GetForegroundWindow() != window) return;
    out[0] = (uint8_t)((key('X') << 7) | (key('C') << 6) | (key('Z') << 5) | (key(VK_RETURN) << 4) |
                       (key('T') << 3) | (key('G') << 2) | (key('F') << 1) | key('H'));
    out[1] = (uint8_t)((key('Q') << 5) | (key('E') << 4) | (key('I') << 3) | (key('K') << 2) |
                       (key('J') << 1) | key('L'));
    out[2] = (uint8_t)(int8_t)(key(VK_RIGHT) ? 80 : key(VK_LEFT) ? -80 : 0);
    out[3] = (uint8_t)(int8_t)(key(VK_UP) ? 80 : key(VK_DOWN) ? -80 : 0);
}

void platform_exit_game_thread(int code) {
    exit_code = code;
    InterlockedExchange(&finished, 1);
    if (window) PostMessageA(window, WM_APP, 0, 0);
    ExitThread((DWORD)code);
}

static DWORD WINAPI thread_main(LPVOID unused) {
    (void)unused;
    game_fn();
    return 0;
}

static void paint(HWND hwnd) {
    PAINTSTRUCT ps;
    RECT rc;
    HDC dc = BeginPaint(hwnd, &ps);
    int w, h;
    GetClientRect(hwnd, &rc);
    if (n64_framebuffer(pixels, MAX_PIXELS, &w, &h)) {
        BITMAPINFO bmi;
        memset(&bmi, 0, sizeof bmi);
        bmi.bmiHeader.biSize = sizeof bmi.bmiHeader;
        bmi.bmiHeader.biWidth = w;
        bmi.bmiHeader.biHeight = -h; /* top-down rows */
        bmi.bmiHeader.biPlanes = 1;
        bmi.bmiHeader.biBitCount = 32;
        bmi.bmiHeader.biCompression = BI_RGB;
        StretchDIBits(dc, 0, 0, rc.right, rc.bottom, 0, 0, w, h, pixels, &bmi, DIB_RGB_COLORS, SRCCOPY);
    } else {
        const char* msg = "Waiting for the program to set up the Video Interface...";
        FillRect(dc, &rc, (HBRUSH)GetStockObject(BLACK_BRUSH));
        SetTextColor(dc, RGB(200, 200, 200));
        SetBkMode(dc, TRANSPARENT);
        DrawTextA(dc, msg, -1, &rc, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    }
    EndPaint(hwnd, &ps);
}

static LRESULT CALLBACK window_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_TIMER:
        if (n64_opts.seconds > 0 && n64_time_ns() > (uint64_t)(n64_opts.seconds * 1e9)) {
            n64_log("time limit of %g s reached", n64_opts.seconds);
            DestroyWindow(hwnd);
            return 0;
        }
        InvalidateRect(hwnd, NULL, FALSE);
        return 0;
    case WM_APP: {
        char title[256];
        snprintf(title, sizeof title, "%s - stopped (exit code %d)", n64_game.title, exit_code);
        SetWindowTextA(hwnd, title);
        return 0;
    }
    case WM_PAINT: paint(hwnd); return 0;
    case WM_ERASEBKGND: return 1;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    default: return DefWindowProcA(hwnd, msg, wp, lp);
    }
}

static int run_window(void) {
    WNDCLASSA wc;
    RECT rc = {0, 0, 320 * n64_opts.scale, 240 * n64_opts.scale};
    char title[256];
    MSG msg;
    memset(&wc, 0, sizeof wc);
    wc.lpfnWndProc = window_proc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.lpszClassName = "N64LabWindow";
    RegisterClassA(&wc);
    AdjustWindowRect(&rc, WS_OVERLAPPEDWINDOW, FALSE);
    snprintf(title, sizeof title, "%s - n64lab", n64_game.title);
    window = CreateWindowA(wc.lpszClassName, title, WS_OVERLAPPEDWINDOW | WS_VISIBLE, CW_USEDEFAULT,
                           CW_USEDEFAULT, rc.right - rc.left, rc.bottom - rc.top, NULL, NULL,
                           wc.hInstance, NULL);
    if (!window) return 0;
    SetTimer(window, 1, 16, NULL);
    while (GetMessageA(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageA(&msg);
    }
    return 1;
}

int platform_run(void (*game_thread)(void)) {
    HANDLE thread;
    game_fn = game_thread;
    /* Recompiled calls nest on the native stack, so give the thread plenty. */
    thread = CreateThread(NULL, 64u << 20, thread_main, NULL, STACK_SIZE_PARAM_IS_A_RESERVATION, NULL);
    if (!thread) {
        n64_log("cannot start the game thread");
        return 1;
    }
    if (!n64_opts.headless && run_window()) {
        n64_final_screenshot();
        fflush(stdout);
        ExitProcess((UINT)exit_code);
    }
    DWORD wait = n64_opts.seconds > 0 ? (DWORD)(n64_opts.seconds * 1000) : INFINITE;
    if (WaitForSingleObject(thread, wait) == WAIT_TIMEOUT) {
        n64_final_screenshot();
        n64_log("time limit of %g s reached", n64_opts.seconds);
        fflush(stdout);
        ExitProcess(0);
    }
    return exit_code;
}
#endif
