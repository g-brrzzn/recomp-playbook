"""Checks tools/post_lift.py on synthetic generated files: apply, idempotence, each edit alone, byte-exact undo, and a
file the function regex does not match. Run: python -I tests/test_post_lift.py"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/post_lift.py"
CONFIG = ROOT / "examples/post_lift_xboxrecomp.json"
NL = chr(10)

CHUNK = NL.join([
    '#include "recomp_types.h"',
    '#include "recomp_funcs.h"',
    "",
    "void sub_00011000(void)",
    "{",
    "    eax = MEM32(esp + 4);",
    "}",
    "",
    "void sub_00011020(void)",
    "{",
    "    g_ebp = esp;",
    "}",
    "",
    "static int helper(int x)",
    "{",
    "    return x;",
    "}",
    "",
])
NO_MATCH = NL.join(['#include "recomp_funcs.h"', "", "static int only_helpers(void) { return 0; }", ""])

failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


def run(gen, *extra, env=None):
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run([sys.executable, "-I", str(TOOL), str(CONFIG), str(gen), *extra], env=e,
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
    return r.returncode


def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        gen = tmp / "gen"
        gen.mkdir()
        (gen / "recomp_0000.c").write_bytes(CHUNK.encode())
        (gen / "recomp_0001.c").write_bytes(NO_MATCH.encode())
        a = gen / "recomp_0000.c"
        b = gen / "recomp_0001.c"

        check(run(gen) == 0, "apply runs")
        text = a.read_text()
        check(text.count("/* post-lift: membase */") == 3, "membase: header plus two functions")
        check(text.count("/* post-lift: regs */") == 3, "regs: header plus two functions")
        check("static int helper(int x)" + NL + "{" + NL + "    return" in text, "helpers are left alone")
        once = a.read_bytes()
        run(gen)
        check(a.read_bytes() == once, "applying twice changes nothing")

        run(gen, env={"MANHUNT_GUEST_REGS": "0"})
        t = a.read_text()
        check("post-lift: membase" in t and "post-lift: regs" not in t, "regs switched off alone")
        run(gen, env={"MANHUNT_MEMBASE_LOCAL": "0"})
        t = a.read_text()
        check("post-lift: regs" in t and "post-lift: membase" not in t, "membase switched off alone")

        run(gen, "--undo")
        check(a.read_bytes() == CHUNK.encode(), "undo restores the file byte for byte")
        check(b.read_bytes().count(b"post-lift") in (0, 2), "a file without functions gets at most its headers")
        run(gen, "--undo")
        check(b.read_bytes() == NO_MATCH.encode(), "undo restores the file without functions")
    finally:
        shutil.rmtree(tmp)
    print("PASS post_lift" if not failures else f"FAIL post_lift ({len(failures)} failures)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
