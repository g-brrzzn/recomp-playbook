/*
 * core_usage.c -- how busy each CPU core is, and every thread of the process with its CPU share.
 *
 * From RTCW (guide 11). For libnx homebrew. Usage:
 *
 *     link with: -Wl,--wrap=threadCreate -Wl,--wrap=threadClose
 *     core_usage_start();          // early, from the main thread
 *     core_usage_log(print);       // every few seconds, e.g. from the frame loop; print is printf-like
 *
 * Lines:
 *     [CPU-CORES] busy core0 46% core1 37% core2 0% (last second)
 *     [CPU-THREAD] main#0 core -1 mask 7 prio 0x2c cpu 84%
 *     [CPU-THREAD] thread#3 core -1 mask 7 prio 0x3b cpu 1% by image+0x1a2b3c image+0x1a0000
 *
 * - Busy per core: the kernel tells a core's idle time (svcGetInfo InfoType_IdleTickCount) only to a thread
 *   running on that core. So a small thread is pinned to each of cores 0-2 (3 is the system's, unless the
 *   title's NPDM grants it), wakes once a second and reads it. They run a few microseconds a second, at a high
 *   priority so they still get to run on a busy core.
 * - Every thread: --wrap=threadCreate catches each thread anyone creates (SDL, Mesa, newlib's pthreads, your
 *   own), with the creating calls from the frame pointer chain (build your code with -fno-omit-frame-pointer).
 *   Its CPU share comes from svcGetInfo InfoType_ThreadTickCount (firmware 13+). tools/profile_report.py
 *   --threads names the image offsets from the ELF.
 * - "core" is the ideal core and "mask" the allowed ones (svcGetThreadCoreMask): where a thread may run, not
 *   where it ran.
 */
#include <stdio.h>
#include <string.h>
#include <switch.h>

#define MAX_THREADS 48
#define APP_CORES 3

typedef struct {
    Thread *thread;     /* NULL for the main thread */
    Handle handle;
    int used, gone;
    u64 callers[4];     /* image offsets of the creating calls */
    u64 last_ticks;
    char name[16];
} ThreadInfo;

static ThreadInfo g_threads[MAX_THREADS];
static Mutex g_lock;
static u64 g_image_base, g_image_end;
static volatile u64 g_idle[APP_CORES], g_span[APP_CORES];
static Thread g_core_threads[APP_CORES];

Result __real_threadCreate(Thread *t, ThreadFunc entry, void *arg, void *stack_mem, size_t stack_sz, int prio, int cpuid);
Result __real_threadClose(Thread *t);

static void find_image(void)
{
    MemoryInfo info;
    u32 page;
    if (!g_image_base && R_SUCCEEDED(svcQueryMemory(&info, &page, (u64)&find_image))) {
        g_image_base = info.addr;
        g_image_end = info.addr + info.size;
    }
}

static void add_thread(Thread *t, Handle h, const char *name, const u64 *callers)
{
    mutexLock(&g_lock);
    for (int i = 0; i < MAX_THREADS; i++) {
        if (!g_threads[i].used || g_threads[i].gone) {
            memset(&g_threads[i], 0, sizeof g_threads[i]);
            g_threads[i].used = 1;
            g_threads[i].thread = t;
            g_threads[i].handle = h;
            snprintf(g_threads[i].name, sizeof g_threads[i].name, "%s", name);
            if (callers) memcpy(g_threads[i].callers, callers, sizeof g_threads[i].callers);
            break;
        }
    }
    mutexUnlock(&g_lock);
}

Result __wrap_threadCreate(Thread *t, ThreadFunc entry, void *arg, void *stack_mem, size_t stack_sz, int prio, int cpuid)
{
    Result rc = __real_threadCreate(t, entry, arg, stack_mem, stack_sz, prio, cpuid);
    if (R_SUCCEEDED(rc)) {
        u64 callers[4] = {0};
        u64 *fp = (u64 *)__builtin_frame_address(0);
        int n = 0;
        find_image();
        for (int depth = 0; fp && depth < 16 && n < 4; depth++) {
            u64 ret = fp[1];
            u64 *next = (u64 *)fp[0];
            if (ret >= g_image_base && ret < g_image_end) callers[n++] = ret - g_image_base;
            if (next <= fp) break;
            fp = next;
        }
        add_thread(t, t->handle, "thread", callers);
    }
    return rc;
}

Result __wrap_threadClose(Thread *t)
{
    mutexLock(&g_lock);
    for (int i = 0; i < MAX_THREADS; i++)
        if (g_threads[i].used && g_threads[i].thread == t) g_threads[i].gone = 1;
    mutexUnlock(&g_lock);
    return __real_threadClose(t);
}

static void core_main(void *arg)
{
    int core = (int)(uintptr_t)arg;
    u64 last_idle = 0, last_tick = armGetSystemTick();
    svcGetInfo(&last_idle, InfoType_IdleTickCount, INVALID_HANDLE, (u64)-1);   /* -1: this core */
    for (;;) {
        u64 idle = 0;
        svcSleepThread(1000000000LL);
        if (R_FAILED(svcGetInfo(&idle, InfoType_IdleTickCount, INVALID_HANDLE, (u64)-1))) return;
        u64 tick = armGetSystemTick();
        g_idle[core] = idle - last_idle;
        g_span[core] = tick - last_tick;
        last_idle = idle;
        last_tick = tick;
    }
}

void core_usage_start(void)
{
    find_image();
    mutexInit(&g_lock);
    add_thread(NULL, threadGetCurHandle(), "main", NULL);
    for (int core = 0; core < APP_CORES; core++)   /* not through the wrap: not listed */
        if (R_SUCCEEDED(__real_threadCreate(&g_core_threads[core], core_main, (void *)(uintptr_t)core, NULL, 0x2000, 0x20, core)))
            threadStart(&g_core_threads[core]);
}

void core_usage_log(int (*print)(const char *fmt, ...))
{
    static u64 last;
    char line[512];
    u64 now = armGetSystemTick(), span = last ? now - last : 0;
    int len = snprintf(line, sizeof line, "[CPU-CORES] busy");
    last = now;
    for (int core = 0; core < APP_CORES; core++) {
        u64 s = g_span[core], idle = g_idle[core] > s ? s : g_idle[core];
        len += s ? snprintf(line + len, sizeof line - len, " core%d %.0f%%", core, 100.0 - 100.0 * (double)idle / (double)s)
                 : snprintf(line + len, sizeof line - len, " core%d ?", core);
    }
    print("%s (last second)\n", line);

    mutexLock(&g_lock);
    for (int i = 0; i < MAX_THREADS; i++) {
        ThreadInfo *t = &g_threads[i];
        u64 ticks = 0, mask = 0;
        s32 ideal = -9, prio = -1;
        if (!t->used || t->gone) continue;
        if (R_FAILED(svcGetInfo(&ticks, InfoType_ThreadTickCount, t->handle, (u64)-1))) { t->gone = 1; continue; }
        svcGetThreadCoreMask(&ideal, &mask, t->handle);
        svcGetThreadPriority(&prio, t->handle);
        len = snprintf(line, sizeof line, "[CPU-THREAD] %s#%d core %d mask %lx prio 0x%x cpu %.0f%%", t->name, i, ideal,
                       (unsigned long)mask, prio, span && t->last_ticks ? 100.0 * (double)(ticks - t->last_ticks) / (double)span : -1.0);
        for (int k = 0; k < 4 && t->callers[k]; k++)
            len += snprintf(line + len, sizeof line - len, "%s image+0x%lx", k ? "" : " by", (unsigned long)t->callers[k]);
        t->last_ticks = ticks;
        print("%s\n", line);
    }
    mutexUnlock(&g_lock);
}
