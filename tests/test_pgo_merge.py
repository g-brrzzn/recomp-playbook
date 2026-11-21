"""Checks tools/pgo_merge.py's stream parsing, renaming and summary fix on synthetic data (no gcov-tool needed).
Run: python -I tests/test_pgo_merge.py"""
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pgo_merge as pm  # noqa: E402

VERSION = b"B52*"
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


def gcda(arcs, runs=0, sum_max=0):
    head = struct.pack("<I", pm.GCDA_MAGIC) + VERSION + b"\0" * 8
    summary = struct.pack("<Ii", pm.TAG_OBJECT_SUMMARY, 8) + struct.pack("<II", runs, sum_max)
    counters = struct.pack("<Ii", pm.TAG_ARC_COUNTERS, 8 * len(arcs)) + struct.pack(f"<{len(arcs)}q", *arcs)
    return head + summary + counters + struct.pack("<Ii", 0, 0)


def gcfn(name, body):
    raw = name.encode() + b"\0"
    return struct.pack("<I", pm.GCFN_MAGIC) + VERSION + struct.pack("<I", len(raw)) + raw + body


def main():
    tmp = Path(tempfile.mkdtemp())
    # the second object's counters contain the gcfn magic on purpose: it must not split the stream there
    stream = gcfn("/build/a/x.gcda", gcda([5, 9])) + gcfn("/build/a/y.gcda", gcda([pm.GCFN_MAGIC, 3]))
    src = tmp / "run.stream"
    src.write_bytes(stream)
    parts = list(pm.split_stream(stream))
    check([n for n, _ in parts] == ["/build/a/x.gcda", "/build/a/y.gcda"], "two objects found by name")
    check(parts[0][1] == gcda([5, 9]), "first object's data is exact")

    dst = tmp / "renamed.stream"
    objects, longest = pm.rename_stream(src, dst, "/build/a", "/p")
    names = [n for n, _ in pm.split_stream(dst.read_bytes())]
    check(objects == 2 and names == ["/p/x.gcda", "/p/y.gcda"], "names renamed")
    check(longest == len("/p/x.gcda"), "longest name reported")

    g = tmp / "x.gcda"
    g.write_bytes(gcda([5, 9]))
    check(pm.max_arc_count(g) == 9, "largest arc count read")
    check(pm.fix_summary(g, 3, 9) == "summary set", "empty summary is set")
    _, at, _ = next(r for r in pm.records(g.read_bytes()) if r[0] == pm.TAG_OBJECT_SUMMARY)
    check(struct.unpack_from("<II", g.read_bytes(), at) == (3, 9), "runs and sum_max written")
    check(pm.fix_summary(g, 5, 99) == "summary kept", "a set summary is kept")
    print("PASS pgo_merge" if not failures else f"FAIL pgo_merge ({len(failures)} failures)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
