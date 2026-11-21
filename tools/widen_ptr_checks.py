"""Rewrite hard-coded guest pointer range checks into calls to one helper, so moving the memory map means editing one header.

From LEGO (log135). Hand-written guard patches in the generated code and checks in the runtime accepted guest pointers
only in fixed ranges (`p < 0x80000000u || p >= 0x94000000u`). When the memory map grew a new range, every one of those
guards rejected the new pointers and the crash showed up far from its cause (guide 03). This script rewrites the two
check shapes, only when the same expression is on both sides:

    X < LO || X >= HI     ->  !HELPER(X)
    X >= LO && X < HI     ->  HELPER(X)

and adds `#include "<header>"` after the first #include of each file it changes (later includes may sit inside #ifdef
blocks). With --extra, wider checks (kernel objects up to 0xC0000000, say) keep their bounds and also accept the extra
range:

    X < 0x80000000u || X >= 0xC0000000u  ->  (!EXTRA(X) && (X < 0x80000000u || X >= 0xC0000000u))

The header is yours, for example:
    static inline bool guest_ptr_ok(uint32_t p) { return (p >= 0x80000000u && p < 0x94000000u) || in_extra(p); }

    python tools/widen_ptr_checks.py --rule 0x80000000:0x94000000=guest_ptr_ok [--rule 0x82000000:0x94000000=image_ptr_ok]
           [--extra 0x80000000:0xC0000000,0xE0000000=in_extra] --include guest_ptr.h [--glob "ppc_recomp.*.cpp"]
           [--check] FILE_OR_DIR...

Idempotent (a rewritten check no longer matches). --check reports and changes nothing; exit 1 if any check is left.
The generated code is regenerated from scratch: run this after every regeneration, and keep the run in the build script.
Read the diff the first time: a check whose bounds mean something else (a size, not a pointer) must not be rewritten.
"""
import argparse
import re
import sys
from pathlib import Path

X = r"([A-Za-z_]\w*(?:(?:\.|->)[A-Za-z_]\w*)*)"


def num(s):
    """Regex for a 32-bit constant as written in C: hex, any case, optional u/U suffix."""
    return "0[xX]0*(?i:" + format(int(s, 16), "x") + ")[uU]?"


def rules_from(args):
    out = []
    for r in args.rule:
        rng, helper = r.split("=")
        lo, hi = rng.split(":")
        rej = re.compile(X + r"\s*<\s*" + num(lo) + r"\s*\|\|\s*\1\s*>=\s*" + num(hi))
        acc = re.compile(X + r"\s*>=\s*" + num(lo) + r"\s*&&\s*\1\s*<\s*" + num(hi))
        out.append((rej, lambda m, h=helper: f"!{h}({m.group(1)})"))
        out.append((acc, lambda m, h=helper: f"{h}({m.group(1)})"))
    for e in args.extra:
        rng, helper = e.split("=")
        lo, his = rng.split(":")
        for hi in his.split(","):
            # the lookbehinds skip checks this script already wrapped (it keeps the old check inside)
            rej = re.compile(r"(?<!&& \()" + X + r"\s*<\s*(" + num(lo) + r")\s*\|\|\s*\1\s*>=\s*(" + num(hi) + ")")
            acc = re.compile(r"(?<!\|\| \()" + X + r"\s*>=\s*(" + num(lo) + r")\s*&&\s*\1\s*<\s*(" + num(hi) + ")")
            out.append((rej, lambda m, h=helper: f"(!{h}({m.group(1)}) && ({m.group(1)} < {m.group(2)} || {m.group(1)} >= {m.group(3)}))"))
            out.append((acc, lambda m, h=helper: f"({h}({m.group(1)}) || ({m.group(1)} >= {m.group(2)} && {m.group(1)} < {m.group(3)}))"))
    return out


def rewrite(text, rules):
    total = 0
    for rx, fn in rules:
        text, n = rx.subn(fn, text)
        total += n
    return text, total


def add_include(text, header):
    line = f'#include "{header}"   // tools/widen_ptr_checks.py'
    if f'"{header}"' in text:
        return text
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    at = next((i for i, l in enumerate(lines[:80]) if l.startswith("#include")), -1) + 1
    lines.insert(at, line)
    return nl.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--rule", action="append", default=[], help="LO:HI=helper")
    ap.add_argument("--extra", action="append", default=[], help="LO:HI[,HI...]=helper")
    ap.add_argument("--include", required=True)
    ap.add_argument("--glob", default="ppc_recomp.*.cpp", help="files taken from a directory")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if not args.rule and not args.extra:
        sys.exit("give at least one --rule or --extra")
    rules = rules_from(args)
    files = []
    for p in args.paths:
        files += sorted(p.glob(args.glob)) if p.is_dir() else [p]
    total = 0
    for f in files:
        text = f.read_bytes().decode("utf-8", errors="surrogateescape")
        new, n = rewrite(text, rules)
        if not n:
            continue
        total += n
        print(f"{f}: {n} checks")
        if not args.check:
            f.write_bytes(add_include(new, args.include).encode("utf-8", errors="surrogateescape"))
    print(f"{total} checks {'to rewrite' if args.check else 'rewritten'}")
    return 1 if args.check and total else 0


if __name__ == "__main__":
    sys.exit(main())
