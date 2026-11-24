"""Checks tools/profile_report.py and tools/ab_compare.py --by on synthetic inputs.
Run: python -I tests/test_profiling.py"""
import contextlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import profile_report  # noqa: E402

NL = chr(10)

# nm -n output: game code, a Mesa function, libnx's wait wrapper.
SYMBOLS = NL.join([
    "0000000000001000 T main",
    "0000000000002000 T RB_SwapBuffers",
    "0000000000003000 T RB_DrawSurfs",
    "0000000000004000 T nouveau_fence_wait",
    "0000000000005000 T svcWaitSynchronization",
    "0000000000006000 T eventWait",
    "0000000000007000 T nwindowDequeueBuffer",
    "0000000000008000 T SDL_CreateThread",
]) + NL

# Two phases, two labels. Busy-waiting in nouveau_fence_wait is running; the dequeue sample sits in an SVC.
PROFILE = NL.join([
    "prof 1 code 100000 900000 period_ms 2",
    "window 0 30000 samples 100 failed 0 dropped 0",
    "phase 0 renderer back end",
    "phase 1 cgame",
    "label 0 A",
    "label 1 B",
    "s 0 0 0 60 4010 2020 1010 0 0 0 0 0 0 0 0 0 0 0 0 0",
    "s 0 1 1 30 5004 6010 7010 3020 1010 0 0 0 0 0 0 0 0 0 0 0",
    "s 1 0 0 10 3010 1010 0 0 0 0 0 0 0 0 0 0 0 0 0 0",
]) + NL

LOG = NL.join([
    "[CPU-CORES] busy core0 46% core1 37% core2 0% (last second)",
    "[CPU-THREAD] thread#3 core -1 mask 7 prio 0x3b cpu 1% by image+0x8010 image+0x1010",
]) + NL


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)
    print("ok:", what)


def main():
    name = profile_report.namer(*profile_report.load_symbols(SYMBOLS))
    with tempfile.TemporaryDirectory() as tmp:
        prof = Path(tmp) / "profile.txt"
        prof.write_text(PROFILE, encoding="utf-8")
        samples = profile_report.read_profile(prof)
        check(len(samples) == 3 and samples[0][0] == "renderer back end" and samples[1][1] == "B", "profile read with phase and label names")

        out = io.StringIO()
        c = profile_report.report(samples, name, out=out)
        check(c["state"]["running"] == 70 and c["state"]["waiting in the kernel"] == 30, "SVC samples count as waiting")
        check(c["work"]["nouveau_fence_wait"] == 60, "a busy wait shows as CPU work, by name")
        check(c["waiter"]["RB_DrawSurfs"] == 30, "the waiting sample is charged to the game function, past the plumbing")
        check(c["wait_in"]["nwindowDequeueBuffer"] == 30, "and to the system call it waited in")
        check(c["incl"]["main"] == 100, "inclusive counts each sample once per function")

        c = profile_report.report(samples, name, label="A", phase="back end", out=io.StringIO())
        check(sum(c["phase"].values()) == 60, "--label and --phase filter")

        log = Path(tmp) / "game.log"
        log.write_text(LOG, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            profile_report.name_threads(log, name, out=out)
        check("by SDL_CreateThread < main" in out.getvalue(), "thread lines get their creators named")

        # ab_compare --by: two scenes in each log, compared scene by scene.
        rx = r"fps (?P<fps>[\d.]+) cpu (?P<cpu>[\d.]+) verts (?P<verts>\d+)"
        a = Path(tmp) / "a.txt"
        b = Path(tmp) / "b.txt"
        a.write_text(NL.join(f"[perf] map forest ab A fps 30 cpu {4 + i % 2} verts 12000" for i in range(6)) + NL +
                     NL.join("[perf] map escape1 ab A fps 30 cpu 6 verts 6000" for _ in range(6)) + NL, encoding="utf-8")
        b.write_text(NL.join("[perf] map forest ab A fps 30 cpu 3 verts 12000" for _ in range(6)) + NL +
                     "[perf] map other ab A fps 60 cpu 1 verts 10" + NL, encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(ROOT / "tools/ab_compare.py"), str(a), str(b), "--regex", rx,
                            "--by", r"map (\S+) ab (\S+)", "--heavy-min", "0"], capture_output=True, text=True)
        check(r.returncode == 0 and "== forest A" in r.stdout and "escape1" not in r.stdout, "--by compares only groups in both logs")
        check("-33.3%" in r.stdout, "--by: forest cpu 4.5 -> 3 is -33.3%")
    print("all profiling checks passed")


if __name__ == "__main__":
    main()
