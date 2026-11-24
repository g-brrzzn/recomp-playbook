/*
 * sampling_profiler.c -- a sampling profiler that runs on the Switch, for libnx homebrew.
 *
 * From RTCW, after LEGO's hw_profiler (guide 06). Usage:
 *
 *     // once, from the thread to profile (usually main), before the game starts:
 *     prof_start(2, "sdmc:/mygame/logs/profile.txt", &g_phase, &g_label);
 *     // as the game runs, the profiled thread names what it is doing:
 *     g_phase = "renderer back end";   // a string literal: only the pointer is copied
 *     g_label = 3;                     // a small index, e.g. the A/B state
 *
 * Every period_ms a thread of its own pauses the target (svcSetThreadActivity), reads its context
 * (svcGetThreadContext3), records pc, lr and the calls that led there, and lets it go on. Samples are
 * counted per (phase, label, call chain); every 30 s the table goes to the file. tools/profile_report.py
 * names the addresses from the ELF of the same build.
 *
 * What it adds to a plain pc sampler:
 * - The call chain follows the frame pointers (x29). Build your own code with -fno-omit-frame-pointer:
 *   code without frame pointers (Mesa, libnx) leaves x29 alone, so a sample deep in the driver still leads
 *   back through the game's calls exactly. x29 then points at the frame of the last function that has one,
 *   so the driver's calls, and the return into that function, are only in the stack below it: a scan of that
 *   part comes first. Each word that points just after a BL/BLR counts as a return address, if the BL went
 *   into the function of the frame found before it: code without frame pointers leaves old return addresses
 *   in its locals. Where the chain is still too short, the whole stack is scanned, unchecked (probably
 *   calling, not exact).
 * - A sample whose pc is at or just after an SVC is the thread blocked in the kernel (a GPU fence, the
 *   swap chain, a mutex, sleep). The report splits waiting from working, and names what waited.
 * - The phase and label tell which part of the frame and which A/B state a sample belongs to.
 *
 * While the target is paused it may hold any lock, so nothing between pause and resume allocates, prints
 * or takes a lock. The writing happens between samples, with the target running.
 */
#include <stdio.h>
#include <string.h>
#include <switch.h>

#define PROF_FRAMES 20          /* pc, lr, then return addresses */
#define PROF_WORDS  2048        /* stack words scanned */
#define PROF_FUNC_MAX 0x10000   /* a function's size, at most: how far below a frame a call may land */
#define PROF_TABLE  (1 << 14)   /* distinct (phase, label, chain) per window */
#define PROF_WINDOW_MS 30000
#define PROF_NAMES  32

typedef struct {
    u32 count;
    u8 used, phase, label, waiting;
    u32 frames[PROF_FRAMES];    /* offsets from the code base, 0 = none */
} ProfEntry;

static ProfEntry g_table[PROF_TABLE];
static u32 g_samples, g_failed, g_dropped;
static u64 g_code_base, g_code_end;
static Handle g_target;
static Thread g_thread;
static int g_period_ms;
static char g_path[256];
static const char *volatile *g_phase_src;
static volatile int *g_label_src;
static const char *g_phases[PROF_NAMES];
static int g_num_phases;

static int phase_index(const char *p)
{
    for (int i = 0; i < g_num_phases; i++)
        if (g_phases[i] == p) return i;
    if (g_num_phases < PROF_NAMES) { g_phases[g_num_phases] = p; return g_num_phases++; }
    return PROF_NAMES - 1;
}

static bool in_code(u64 v) { return v >= g_code_base && v < g_code_end; }

static bool follows_call(u64 v)
{
    if ((v & 3) || v < g_code_base + 4 || v >= g_code_end) return false;
    u32 insn = *(const u32 *)(v - 4);
    return (insn & 0xFC000000u) == 0x94000000u || (insn & 0xFFFFFC1Fu) == 0xD63F0000u;   /* BL, BLR */
}

/* The target of the BL just before return address r; 0 for a BLR (through a pointer: it tells nothing). */
static u64 call_target(u64 r)
{
    u32 insn = *(const u32 *)(r - 4);
    if ((insn & 0xFC000000u) != 0x94000000u) return 0;
    return r - 4 + (u64)((s64)((s32)(insn << 6) >> 6) * 4);
}

/* Whether a call to target can have led to code at inner (inner is in the function at target). */
static bool leads(u64 target, u64 inner) { return target && target <= inner && inner - target < PROF_FUNC_MAX; }

static int append(u32 *frames, int n, u64 v)
{
    u32 off = (u32)(v - g_code_base);
    if (n < PROF_FRAMES && off != frames[n - 1] && off != frames[1]) frames[n++] = off;
    return n;
}

/* The stack below the last frame record: the calls made by code without frame pointers. A word counts
 * when the BL before it went into the function of the frame found before it. A BLR can't be checked: it
 * waits until a later checked call (or the frame chain's first return) leads into it. */
static int scan_below(u32 *frames, int n, const ThreadContext *ctx, u64 fp, u64 limit)
{
    const u64 *word = (const u64 *)(ctx->sp & ~(u64)7);
    u64 known[2] = {ctx->pc.x, ctx->lr}, pending[3];
    int num_known = 2, num_pending = 0;
    for (int w = 0; word + w < (const u64 *)fp && w < PROF_WORDS && n < PROF_FRAMES - 6; w++) {
        u64 r = word[w], target;
        if (!follows_call(r)) continue;
        if (!(target = call_target(r))) {
            if (num_pending == 3) { memmove(pending, pending + 1, 2 * sizeof pending[0]); num_pending--; }
            pending[num_pending++] = r;
            continue;
        }
        int hit = -1;
        for (int k = 0; k < num_known; k++) if (leads(target, known[k])) hit = -2;   /* the BLRs were old words */
        for (int k = num_pending - 1; hit == -1 && k >= 0; k--) if (leads(target, pending[k])) hit = k;
        if (hit == -1) continue;   /* an old word, left from earlier calls */
        for (int k = 0; k <= hit; k++) n = append(frames, n, pending[k]);
        n = append(frames, n, r);
        known[0] = r; num_known = 1; num_pending = 0;
    }
    if (num_pending && fp + 16 <= limit && follows_call(((const u64 *)fp)[1])) {
        u64 target = call_target(((const u64 *)fp)[1]);
        int hit = -1;
        for (int k = num_pending - 1; hit == -1 && k >= 0; k--) if (leads(target, pending[k])) hit = k;
        for (int k = 0; k <= hit; k++) n = append(frames, n, pending[k]);
    }
    return n;
}

/* The saved pc of a thread in a syscall is the SVC itself or the instruction after it. */
static bool at_svc(u64 pc)
{
    if ((pc & 3) || pc < g_code_base + 4 || pc + 4 > g_code_end) return false;
    return (*(const u32 *)(pc - 4) & 0xFFE0001Fu) == 0xD4000001u || (*(const u32 *)pc & 0xFFE0001Fu) == 0xD4000001u;
}

static void add(int phase, int label, int waiting, const u32 *frames)
{
    u32 h = 2166136261u ^ (u32)phase ^ ((u32)label << 8) ^ ((u32)waiting << 16);
    for (int i = 0; i < PROF_FRAMES; i++) h = (h ^ frames[i]) * 16777619u;
    for (u32 probe = 0; probe < 64; probe++) {
        ProfEntry *e = &g_table[(h + probe) & (PROF_TABLE - 1)];
        if (!e->used) {
            e->used = 1; e->phase = (u8)phase; e->label = (u8)label; e->waiting = (u8)waiting;
            memcpy(e->frames, frames, sizeof e->frames);
            e->count = 1;
            return;
        }
        if (e->phase == phase && e->label == label && e->waiting == waiting && !memcmp(e->frames, frames, sizeof e->frames)) {
            e->count++;
            return;
        }
    }
    g_dropped++;
}

static void sample(void)
{
    ThreadContext ctx;
    u32 frames[PROF_FRAMES] = {0};
    MemoryInfo mi;
    u32 page;
    int n = 2, waiting = 0;
    int phase = phase_index(g_phase_src ? *g_phase_src : "-");
    int label = g_label_src ? *g_label_src : 0;

    if (R_FAILED(svcSetThreadActivity(g_target, ThreadActivity_Paused))) { g_failed++; return; }
    Result rc = svcGetThreadContext3(&ctx, g_target);
    for (int retry = 0; R_FAILED(rc) && retry < 3; retry++) {   /* still leaving its core */
        svcSleepThread(0);
        rc = svcGetThreadContext3(&ctx, g_target);
    }
    if (R_SUCCEEDED(rc)) {
        if (in_code(ctx.pc.x)) { frames[0] = (u32)(ctx.pc.x - g_code_base); waiting = at_svc(ctx.pc.x); }
        if (in_code(ctx.lr)) frames[1] = (u32)(ctx.lr - g_code_base);
        if (R_SUCCEEDED(svcQueryMemory(&mi, &page, ctx.sp)) && (mi.perm & Perm_R)) {
            const u64 limit = mi.addr + mi.size;
            u64 fp = ctx.fp;
            if (fp > ctx.sp && fp <= limit) n = scan_below(frames, n, &ctx, fp, limit);
            while (n < PROF_FRAMES && fp >= ctx.sp && fp + 16 <= limit && !(fp & 7)) {
                const u64 *record = (const u64 *)fp;
                if (in_code(record[1])) {
                    u32 off = (u32)(record[1] - g_code_base);
                    if (off != frames[n - 1] && off != frames[1]) frames[n++] = off;
                }
                if (record[0] <= fp) break;   /* the chain goes up the stack, or ends with 0 */
                fp = record[0];
            }
            const u64 *word = (const u64 *)(ctx.sp & ~(u64)7);
            for (int w = 0; n < 4 && w < PROF_WORDS && (u64)(word + 1) <= limit; w++, word++) {
                if (follows_call(*word)) {
                    u32 off = (u32)(*word - g_code_base);
                    if (off != frames[n - 1] && off != frames[1]) frames[n++] = off;
                }
            }
        }
    }
    svcSetThreadActivity(g_target, ThreadActivity_Runnable);
    if (R_SUCCEEDED(rc)) { add(phase, label, waiting, frames); g_samples++; }
    else g_failed++;
}

static void write_window(FILE *f, u64 start_ms, u64 end_ms)
{
    fprintf(f, "window %lu %lu samples %u failed %u dropped %u\n", (unsigned long)start_ms, (unsigned long)end_ms,
            g_samples, g_failed, g_dropped);
    for (int i = 0; i < g_num_phases; i++) fprintf(f, "phase %d %s\n", i, g_phases[i]);
    for (int i = 0; i < PROF_TABLE; i++) {
        ProfEntry *e = &g_table[i];
        if (!e->used) continue;
        fprintf(f, "s %u %u %u %u", e->phase, e->label, e->waiting, e->count);
        for (int k = 0; k < PROF_FRAMES; k++) fprintf(f, " %x", e->frames[k]);
        fputc('\n', f);
        e->used = 0;
    }
    fflush(f);
    g_samples = g_failed = g_dropped = 0;
}

static void prof_main(void *arg)
{
    (void)arg;
    FILE *f = fopen(g_path, "w");
    if (!f) return;
    setvbuf(f, NULL, _IOFBF, 64 * 1024);
    fprintf(f, "prof 1 code %lx %lx period_ms %d\n", (unsigned long)g_code_base, (unsigned long)g_code_end, g_period_ms);
    fflush(f);
    u64 start = armTicksToNs(armGetSystemTick()) / 1000000;
    for (;;) {
        svcSleepThread((s64)g_period_ms * 1000000);
        sample();
        u64 now = armTicksToNs(armGetSystemTick()) / 1000000;
        if (now - start >= PROF_WINDOW_MS) { write_window(f, start, now); start = now; }
    }
}

/* Profiles the calling thread. phase and label may be NULL. Returns the thread start result. */
Result prof_start(int period_ms, const char *path, const char *volatile *phase, volatile int *label)
{
    MemoryInfo info;
    u32 page;
    if (period_ms <= 0) return 0;
    g_period_ms = period_ms;
    g_target = threadGetCurHandle();
    g_phase_src = phase;
    g_label_src = label;
    snprintf(g_path, sizeof g_path, "%s", path);
    if (R_SUCCEEDED(svcQueryMemory(&info, &page, (u64)&prof_start))) {   /* the code region holding this file */
        g_code_base = info.addr;
        g_code_end = info.addr + info.size;
    }
    /* Above a usual main thread (0x2C), on a core of its own; it sleeps almost all the time. */
    Result rc = threadCreate(&g_thread, prof_main, NULL, NULL, 0x8000, 0x2A, 2);
    if (R_SUCCEEDED(rc)) rc = threadStart(&g_thread);
    return rc;
}
