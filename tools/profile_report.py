"""Name the samples of tools/sampling_profiler.c, or the thread lines of tools/core_usage.c.

    python tools/profile_report.py profile.txt game.elf [--label N] [--phase TEXT] [--top 25]
    python tools/profile_report.py game-log.txt game.elf --threads
    (--symbols nm.txt instead of the ELF: the output of `aarch64-none-elf-nm -n -C --defined-only game.elf`)

The ELF must come from the same build as the NRO that ran: keep it with every build you test.

For the samples kept by --label (the label index) and --phase (a part of the phase name), it prints the split
by phase and by label, how many waited in the kernel, where the thread was (all samples, then running ones only:
the CPU work), inclusive counts (anywhere in the chain), and for waiting samples the first function outside the
driver and system plumbing (what waited) and the driver or system call it waited in.

With --threads, the first file is the game's log: its [CPU-CORES] / [CPU-THREAD] lines are printed with each
thread's creating calls named.
"""
import argparse
import bisect
import collections
import os
import re
import shutil
import subprocess
import sys

# Names that are plumbing, not the caller you want to see. Mesa/nouveau and libnx on the Switch.
PLUMBING = ("svc", "_", "mutex", "condvar", "rmutex", "event", "wait", "nv", "binder", "usleep", "fs",
            "st_", "nvc0", "nouveau", "PUSH", "pipe", "vbo_", "u_", "cli_", "thrd", "cnd_", "mtx_",
            "pushbuf", "parcel", "update_program", "_mesa", "glsl", "thread", "pthread",
            "nwindow", "bq", "framebuffer", "switch_")


def find_nm():
    exe = "aarch64-none-elf-nm" + (".exe" if os.name == "nt" else "")
    found = shutil.which(exe)
    if found:
        return found
    for root in (os.environ.get("DEVKITPRO", ""), r"C:\devkitPro\msys2\opt\devkitpro", "/opt/devkitpro"):
        cand = os.path.join(root, "devkitA64", "bin", exe)
        if root and os.path.exists(cand):
            return cand
    sys.exit("aarch64-none-elf-nm not found: set DEVKITPRO, or pass --symbols")


def load_symbols(text):
    addrs, names = [], []
    for line in text.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[1] in "tTwW":
            addrs.append(int(parts[0], 16))
            names.append(parts[2])
    return addrs, names


def namer(addrs, names):
    def name(off):
        if not off:
            return "?"
        i = bisect.bisect_right(addrs, off) - 1
        return names[i] if i >= 0 else "0x%x" % off
    return name


def read_profile(path):
    samples, phases, labels = [], {}, {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "phase":
                phases[int(p[1])] = " ".join(p[2:])
            elif p[0] == "label":
                labels[int(p[1])] = " ".join(p[2:])
            elif p[0] == "s":
                ph, lb, wt, n = int(p[1]), int(p[2]), int(p[3]), int(p[4])
                samples.append((phases.get(ph, "?%d" % ph), labels.get(lb, str(lb)), wt, n, [int(x, 16) for x in p[5:]]))
    return samples


def report(samples, name, label=None, phase=None, top=25, out=sys.stdout):
    keep = [s for s in samples if (label is None or s[1] == label) and (not phase or phase in s[0])]
    total = sum(s[3] for s in keep)
    print("%d samples kept of %d" % (total, sum(s[3] for s in samples)), file=out)
    if not total:
        return {}
    counters = {k: collections.Counter() for k in ("phase", "label", "state", "self", "work", "incl", "waiter", "wait_in")}
    for ph, lb, wt, n, frames in keep:
        wt = wt or name(frames[0]).startswith("svc")   # inside a libnx syscall wrapper
        counters["phase"][ph] += n
        counters["label"][lb] += n
        counters["state"]["waiting in the kernel" if wt else "running"] += n
        counters["self"][name(frames[0]) + (" [wait]" if wt else "")] += n
        if not wt:
            counters["work"][name(frames[0])] += n
        for fn in {name(o) for o in frames if o}:
            counters["incl"][fn] += n
        if wt:
            chain = [name(o) for o in frames[1:] if o]
            counters["waiter"][next((c for c in chain if not c.startswith(PLUMBING)), "(deeper than the chain)")] += n
            counters["wait_in"][next((c for c in chain if not c.startswith(("svc", "wait", "event", "_"))), "?")] += n
    titles = [("phase", "By phase"), ("label", "By label"), ("state", "Running or waiting"),
              ("self", "Where the thread was"), ("work", "Where it was, running samples only (CPU work)"),
              ("incl", "Inclusive (anywhere in the chain)"), ("waiter", "Waiting: the function that waited"),
              ("wait_in", "Waiting: in which driver or system call")]
    for key, title in titles:
        if not counters[key]:
            continue
        print("\n" + title, file=out)
        for k, n in counters[key].most_common(top):
            print("  %5.1f%%  %7d  %s" % (100.0 * n / total, n, k), file=out)
    return counters


def name_threads(log, name, out=sys.stdout):
    with open(log, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith(("[CPU-CORES]", "[CPU-THREAD]")):
                continue
            line = re.sub(r"image\+0x([0-9a-f]+)", lambda m: name(int(m.group(1), 16)), line.rstrip())
            if " by " in line:
                head, _, chain = line.partition(" by ")
                calls = chain.split()
                useful = [c for c in calls if not c.startswith(PLUMBING)] or calls
                line = head + " by " + " < ".join(useful[:3])
            print(line, file=out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("elf", nargs="?")
    ap.add_argument("--symbols", help="nm output instead of running nm on the ELF")
    ap.add_argument("--label")
    ap.add_argument("--phase")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--threads", action="store_true")
    args = ap.parse_args()
    if args.symbols:
        with open(args.symbols, encoding="utf-8") as f:
            text = f.read()
    elif args.elf:
        text = subprocess.run([find_nm(), "-n", "-C", "--defined-only", args.elf], capture_output=True, text=True, check=True).stdout
    else:
        sys.exit("give the ELF or --symbols")
    name = namer(*load_symbols(text))
    if args.threads:
        name_threads(args.file, name)
    else:
        report(read_profile(args.file), name, args.label, args.phase, args.top)


if __name__ == "__main__":
    main()
