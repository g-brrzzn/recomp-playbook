// Cooperative guest scheduler: the "gone" guard and a stall watchdog. From LEGO (log130, guide 11).
//
// Runtimes that run guest threads one at a time under a turn (a GIL with explicit hand-offs) hang for good when the turn
// goes to a thread that will never take it. In LEGO the title movie's player resumed its threads after they had exited;
// KeResumeThread put an exited id back in the rotation and every guest thread then waited for the turn (1 run in 5).
// Two pieces fixed and exposed it:
//   1. sched_leave marks the id gone, and sched_add refuses a gone id (ids are never reused). Logged, a few times.
//   2. A watchdog thread: when the turn has not moved for 2 s it prints the scheduler's state once per stall, and if the
//      turn sits with nobody while a thread is ready, with a thread that is gone or off the rotation, or with a holder
//      that itself waits for the turn (a lost wake-up), it hands the turn on. Cheap; keep it behind a switch.
// Confirmed on the console (LEGO run 124: the refusal lines printed, the game went back to the title).
//
// The scheduler below is a minimal stand-in so the file compiles alone (c++ -std=c++17 -c sched_watchdog.cpp); merge
// the two marked pieces into your own scheduler. Switch name: SCHEDWATCH=0 turns the watchdog off.
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <thread>

namespace sched {

constexpr int kMax = 64;
std::mutex mtx;
std::condition_variable cv;
int turn = -1;                    // id holding the turn, -1 = nobody
int count = 0;                    // ids in use: 0 .. count-1
bool alive[kMax], runnable[kMax], waiting[kMax];
bool gone[kMax];                  // (1) set when a thread returns, never cleared
std::atomic<uint64_t> moves{0};   // bump on every turn change

int next_locked(int from) {       // round robin over alive, runnable ids
    for (int k = 1; k <= count; ++k) {
        int i = (from + k) % (count ? count : 1);
        if (alive[i] && runnable[i]) return i;
    }
    return -1;
}

void set_turn_locked(int id) { turn = id; moves.fetch_add(1); cv.notify_all(); }

// (1) A resume of a thread that has exited must not bring its id back.
void add(int id) {
    if (id < 0 || id >= kMax) return;
    std::lock_guard<std::mutex> lk(mtx);
    if (gone[id]) {
        static int told = 0;
        if (told++ < 8) { std::printf("[SCHED] slot %d not added again: its thread has returned\n", id); std::fflush(stdout); }
        return;
    }
    if (id >= count) count = id + 1;
    alive[id] = runnable[id] = true;
    if (turn == -1) set_turn_locked(id);
}

void leave(int id) {
    if (id < 0 || id >= kMax) return;
    std::lock_guard<std::mutex> lk(mtx);
    alive[id] = runnable[id] = false;
    gone[id] = true;
    if (turn == id) set_turn_locked(next_locked(id));
}

// (2) Start once, e.g. from the first thread registration.
void watchdog_start() {
    static std::atomic<bool> started{false};
    if (started.exchange(true)) return;
    const char* e = std::getenv("SCHEDWATCH");
    if (e && e[0] == '0') return;
    std::thread([] {
        uint64_t last = moves.load();
        auto since = std::chrono::steady_clock::now();
        bool told = false;
        for (;;) {
            std::this_thread::sleep_for(std::chrono::milliseconds(250));
            if (moves.load() != last) { last = moves.load(); since = std::chrono::steady_clock::now(); told = false; continue; }
            if (std::chrono::steady_clock::now() - since < std::chrono::seconds(2)) continue;
            std::lock_guard<std::mutex> lk(mtx);
            int ready = 0, waiters = 0;
            for (int i = 0; i < count; ++i) { ready += alive[i] && runnable[i]; waiters += waiting[i]; }
            const bool holder_ok = turn >= 0 && turn < kMax && alive[turn] && runnable[turn];
            const bool stuck = (turn < 0 && ready > 0) || (turn >= 0 && !holder_ok) || (holder_ok && waiting[turn]);
            if (!told) {   // once per stall: who holds the turn, and every thread as alive/runnable/waiting
                char b[1024];
                int k = std::snprintf(b, sizeof b, "[SCHEDWATCH] no turn change for 2 s: turn %d%s, %d ready, %d waiting |",
                                      turn, holder_ok ? "" : " not ready", ready, waiters);
                for (int i = 0; i < count && k < 960; ++i)
                    if (alive[i] || waiting[i])
                        k += std::snprintf(b + k, sizeof b - k, " %d:%c%c%c", i, alive[i] ? 'a' : '-', runnable[i] ? 'r' : '-', waiting[i] ? 'w' : '-');
                std::puts(b);
                std::fflush(stdout);
                told = true;
            }
            if (!stuck) continue;
            const int n = next_locked(turn >= 0 ? turn : 0);
            if (n >= 0 && n != turn) {
                set_turn_locked(n);
                std::printf("[SCHEDWATCH] turn handed to %d\n", n);
                std::fflush(stdout);
            } else {
                cv.notify_all();   // the holder waits for its own turn: wake it again
            }
        }
    }).detach();
}

}  // namespace sched
