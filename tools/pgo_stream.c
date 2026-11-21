/*
 * PGO counts from a running instrumented Switch build (libnx, devkitA64 GCC 12+).
 *
 * Compile every object with
 *     -fprofile-generate -fprofile-update=single -fno-profile-values -fprofile-info-section=gcov_info
 * Each object then registers its counters in the section "gcov_info", and libgcov writes nothing at exit (its exit
 * path assumes a host file system, and a homebrew title usually ends from HOME anyway). This file streams all of
 * them into one file with __gcov_info_to_gcda() (gcov.h):
 *     PGO_DIR/PGO_PREFIX_<run id>.stream
 * replaced by each snapshot (counts only grow, so the latest snapshot holds the whole launch). tools/pgo_merge.py
 * turns the streams into .gcda files for the -fprofile-use build.
 *
 * Call pgo_start() once early (after the SD card is mounted), and pgo_snapshot("exit") on any exit path you control.
 * Build this file only into the instrumented build (define PGO_GENERATE there).
 *
 * Notes from the two ports:
 *  - The thread priority must be allowed: 0x3F is not (the thread never ran in the first try); 0x3B is the lowest
 *    allowed for a homebrew thread here. The creation result is logged so a failure shows.
 *  - A snapshot took about 70 ms for 119 objects (one port) and runs every 60 s; another port used 180 s for 657.
 */
#ifdef PGO_GENERATE
#include <gcov.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <switch.h>

#ifndef PGO_DIR
#define PGO_DIR "sdmc:/switch/mygame/pgo"
#endif
#ifndef PGO_PREFIX
#define PGO_PREFIX "mygame"
#endif
#ifndef PGO_PERIOD_S
#define PGO_PERIOD_S 60
#endif

extern const struct gcov_info *const __start_gcov_info[] __attribute__((weak));
extern const struct gcov_info *const __stop_gcov_info[] __attribute__((weak));

static Mutex s_mutex;
static unsigned long long s_run;
static unsigned s_snapshots;

static void dump_fn(const void *data, unsigned length, void *arg) { fwrite(data, 1, length, (FILE *)arg); }
static void filename_fn(const char *name, void *arg) { __gcov_filename_to_gcfn(name, dump_fn, arg); }
static void *allocate_fn(unsigned length, void *arg) { (void)arg; return malloc(length); }

void pgo_snapshot(const char *why)
{
    if (!__start_gcov_info || !__stop_gcov_info)
        return;
    mutexLock(&s_mutex);
    char path[192], tmp[200];
    snprintf(path, sizeof path, PGO_DIR "/" PGO_PREFIX "_%016llX.stream", s_run);
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    const u64 t0 = armGetSystemTick();
    FILE *f = fopen(tmp, "wb");
    if (!f) {
        printf("[PGO] cannot open %s\n", tmp);
        mutexUnlock(&s_mutex);
        return;
    }
    static char buffer[1 << 20];
    setvbuf(f, buffer, _IOFBF, sizeof buffer);
    unsigned objects = 0;
    for (const struct gcov_info *const *p = __start_gcov_info; p < __stop_gcov_info; ++p, ++objects)
        __gcov_info_to_gcda(*p, filename_fn, dump_fn, allocate_fn, f);
    const long bytes = ftell(f);
    const int ok = fclose(f) == 0;
    remove(path);
    const int renamed = ok && rename(tmp, path) == 0;   /* a cut write never replaces a good snapshot */
    s_snapshots++;
    printf("[PGO] snapshot %u (%s): %u objects, %.1f MB, %llu ms, %s\n", s_snapshots, why, objects,
           bytes / 1048576.0, (unsigned long long)(armTicksToNs(armGetSystemTick() - t0) / 1000000ull),
           renamed ? path : "WRITE FAILED");
    mutexUnlock(&s_mutex);
}

static void pgo_thread(void *arg)
{
    (void)arg;
    for (;;) {
        svcSleepThread((s64)PGO_PERIOD_S * 1000000000ll);
        pgo_snapshot("periodic");
    }
}

void pgo_start(void)
{
    s_run = armGetSystemTick();
    mutexInit(&s_mutex);
    mkdir(PGO_DIR, 0777);
    const long n = (__start_gcov_info && __stop_gcov_info) ? (long)(__stop_gcov_info - __start_gcov_info) : -1;
    printf("[PGO] instrumented build: %ld objects registered, run %016llX\n", n, s_run);
    static Thread t;
    static const int prios[] = {0x2C, 0x3B};
    Result rc = 1;
    for (unsigned i = 0; i < sizeof prios / sizeof prios[0] && R_FAILED(rc); i++) {
        rc = threadCreate(&t, pgo_thread, NULL, NULL, 0x10000, prios[i], -2);
        if (R_SUCCEEDED(rc))
            rc = threadStart(&t);
    }
    printf("[PGO] snapshot thread rc=0x%X (every %d s)\n", rc, PGO_PERIOD_S);
}
#endif
