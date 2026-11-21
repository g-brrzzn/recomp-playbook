"""Compare two console logs of the same scripted run (build a against build b), on heavy-scene samples only.

    python tools/ab_compare.py log-a.txt log-b.txt [--regex R] [--heavy-field verts] [--heavy-min 20000]

The default regex reads the periodic [perf] line of the Manhunt port:
    [perf] 2.0s fps 31.5 max 48ms slow 3 | per frame 31.7ms: draws 940 verts 61234 ... | gl draw 9.1 ...
    ... cpu main 12% guest 88% gl 41% audio 5% apu 45%
Pass --regex with named groups for another port. Every named group becomes a column; the medians are taken over the
samples whose --heavy-field is above --heavy-min (the gameplay part, not menus or loading).

A single pair of runs is noisy (a scripted route drifts, so scenes differ a little). Run a, b, a, b at the same clocks
before trusting a difference under about 5 %, and check the draws column: more draws per frame means a heavier scene.
"""
import argparse
import re
import statistics
import sys
from pathlib import Path

DEFAULT = (r"\[perf\] (?P<secs>[\d.]+)s fps (?P<fps>[\d.]+) max (?P<max_ms>\d+)ms slow (?P<slow>\d+) \| per frame "
           r"[\d.]+ms: draws (?P<draws>[\d.]+) verts (?P<verts>[\d.]+).*?\| gl draw (?P<gl_draw_ms>[\d.]+).*?"
           r"cpu main \d+% guest (?P<guest_cpu>\d+)% gl (?P<gl_cpu>\d+)% audio \d+% apu (?P<apu_cpu>\d+)%")


def samples(path, rx):
    rows = []
    for line in Path(path).read_text("utf-8", "replace").splitlines():
        m = rx.search(line)
        if m:
            rows.append({k: float(v) for k, v in m.groupdict().items() if v is not None})
    return rows


def medians(rows, field, minimum):
    heavy = [r for r in rows if r.get(field, 0) > minimum]
    keys = [k for k in (heavy[0] if heavy else {}) if k != "secs"]
    out = {"samples": len(rows), "heavy": len(heavy)}
    for k in keys:
        out[k] = round(statistics.median(r[k] for r in heavy), 3)
    if heavy and "gl_draw_ms" in keys and "draws" in keys:
        out["gl_ms_per_draw"] = round(statistics.median(r["gl_draw_ms"] / r["draws"] for r in heavy if r["draws"]), 4)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--regex", default=DEFAULT)
    ap.add_argument("--heavy-field", default="verts")
    ap.add_argument("--heavy-min", type=float, default=20000)
    args = ap.parse_args()
    rx = re.compile(args.regex)
    a = medians(samples(args.a, rx), args.heavy_field, args.heavy_min)
    b = medians(samples(args.b, rx), args.heavy_field, args.heavy_min)
    if not a["heavy"] or not b["heavy"]:
        sys.exit(f"not enough heavy samples (a: {a['heavy']}, b: {b['heavy']}); did the route reach gameplay?")
    print(f"{'':16}{'a':>10}{'b':>10}{'b vs a':>10}")
    for k in a:
        if k not in b:
            continue
        x, y = a[k], b[k]
        rel = f"{(y - x) / x * 100:+.1f}%" if x else ""
        print(f"{k:16}{x:>10}{y:>10}{rel:>10}")
    print("\nfps up and guest_cpu down favour b. More draws per frame means a heavier scene: then the runs differ.")


if __name__ == "__main__":
    main()
