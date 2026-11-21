"""Checks tools/replay_check.py, tools/widen_ptr_checks.py and tools/stage_console.py on synthetic inputs.
Run: python -I tests/test_replay_and_staging.py"""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import replay_check  # noqa: E402
import stage_console  # noqa: E402
import widen_ptr_checks  # noqa: E402

NL = chr(10)
BS = chr(92)
CFG = json.loads((ROOT / "examples/replay_check.json").read_text(encoding="utf-8"))


def fake_log(hub_gap, draws):
    lines = [
        "boot",
        f"[LEVEL] levels{BS}hub (frame 10)",
        f"[SCRIPT] line 3 frameset at 1.0 s (level levels{BS}hub, light frames, frame 100)",
        f"[SCRIPT] line 9 frameset at 9.0 s (level levels{BS}hub, play frames, frame {100 + hub_gap})",
        f"[WORK] per replay (60): nvc0 draws {draws}, vertices 40.0 k, vertex program 12.0 KB, pixel program 3.0 KB (x) | guest calls 190 k",
        "[WORK] per replay (60): nvc0 draws 20, vertices 0.0 k, vertex program 1.0 KB, pixel program 1.0 KB (x) | guest calls 5 k",
        f"[LEVEL] levels{BS}swamp (frame 2000)",
        f"[SCRIPT] line 20 frameset at 30 s (level levels{BS}swamp, play frames, frame 2100)",
        f"[SCRIPT] line 40 frameset at 90 s (level levels{BS}swamp, light frames, frame 6352)",
        "[SCRIPT] done",
    ]
    return lines


def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a)
    return r, buf.getvalue()


def test_replay_check():
    base = replay_check.summarize(fake_log(796, 300), CFG)
    assert base["result"] == "done", base
    assert base["gaps"] == ["hub light: 796 frames", "swamp play: 4252 frames"], base["gaps"]
    assert base["levels"] == [["hub", 10], ["swamp", 2000]], base["levels"]
    assert set(base["work"]) == {"hub", "hub (light)"}, base["work"]
    assert base["work"]["hub"]["draws"] == 300.0
    (ok, moved), _ = quiet(replay_check.report, replay_check.summarize(fake_log(797, 302), CFG), base, CFG)
    assert ok and not moved, "1 frame and 0.7 % are within tolerance"
    (ok, moved), out = quiet(replay_check.report, replay_check.summarize(fake_log(900, 300), CFG), base, CFG)
    assert not ok and "DIFFERENT" in out, out
    (ok, moved), _ = quiet(replay_check.report, replay_check.summarize(fake_log(796, 360), CFG), base, CFG)
    assert ok and moved == ["hub draws +20 %"], moved
    crashed = fake_log(796, 300)[:-1] + ["[CRASH] data abort"]
    (ok, _), _ = quiet(replay_check.report, replay_check.summarize(crashed, CFG), base, CFG)
    assert not ok


SRC = NL.join([
    "#include <stdint.h>",
    "#ifdef _WIN32",
    "#include <windows.h>",
    "#endif",
    "void f(uint32_t p, uint32_t q) {",
    "    if (p < 0x80000000u || p >= 0x94000000u) return;",
    "    if (ctx.r3.u32 >= 0x82000000 && ctx.r3.u32 < 0x94000000u) g();",
    "    if (q < 0x80000000u || q >= 0xC0000000u) return;",
    "    if (p < 0x80000000u || q >= 0x94000000u) return;   // two expressions: left alone",
    "}",
    ""])


def test_widen():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "ppc_recomp.1.cpp"
        f.write_bytes(SRC.replace(NL, chr(13) + NL).encode())
        argv = ["--rule", "0x80000000:0x94000000=gp80", "--rule", "0x82000000:0x94000000=gp82",
                "--extra", "0x80000000:0xC0000000=in_extra", "--include", "gp.h", d]
        (rc, out) = quiet(widen_ptr_checks.main, ["--check"] + argv)
        assert rc == 1 and "3 checks to rewrite" in out, out
        assert f.read_bytes().decode() == SRC.replace(NL, chr(13) + NL), "--check changed the file"
        rc, out = quiet(widen_ptr_checks.main, argv)
        text = f.read_bytes().decode()
        assert "if (!gp80(p)) return;" in text, text
        assert "if (gp82(ctx.r3.u32)) g();" in text, text
        assert "(!in_extra(q) && (q < 0x80000000u || q >= 0xC0000000u))" in text, text
        assert "p < 0x80000000u || q >= 0x94000000u" in text
        lines = text.split(chr(13) + NL)
        assert lines[1].startswith('#include "gp.h"'), lines[:3]
        assert NL not in text.replace(chr(13) + NL, ""), "line endings mixed"
        rc, out = quiet(widen_ptr_checks.main, ["--check"] + argv)
        assert rc == 0 and "0 checks" in out, "not idempotent: " + out


def test_stage():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "build").mkdir()
        (d / "build/game.elf").write_bytes(b"ELF" * 100)
        time.sleep(0.05)
        (d / "build/game.nro").write_bytes(b"NRO" * 100)
        nacp = bytearray(0x4000)
        nacp[0x3060:0x3060 + 11] = b"0.1.0-log99"
        (d / "build/game.nacp").write_bytes(bytes(nacp))
        (d / "env.txt").write_bytes(b"A=1" + NL.encode())
        (d / "scripts").mkdir()
        (d / "scripts/route.txt").write_text("100:A", encoding="utf-8")
        cfg = {"nro": "build/game.nro", "elf": "build/game.elf", "nacp": "build/game.nacp", "name": "game",
               "sd": "sd", "keep_dir": "keep", "profile": "env.txt", "profile_dest": "game/env.txt",
               "nro_dest": "switch/game/game.nro", "files": [{"src": "scripts/*.txt", "dest": "game/tests"}]}
        (d / "cfg.json").write_text(json.dumps(cfg), encoding="utf-8")
        try:
            quiet(stage_console.main, [str(d / "cfg.json"), "log98"])
            raise AssertionError("staged a build with the wrong label")
        except SystemExit as e:
            assert "not ...log98" in str(e), e
        rc, out = quiet(stage_console.main, [str(d / "cfg.json"), "log99", "--set", "SCRIPT=route.txt"])
        res = json.loads(out)
        assert sorted(res["changed_on_card"]) == ["game/env.txt", "game/tests/route.txt", "switch/game/game.nro"], res
        assert (d / "sd/game/env.txt").read_bytes().endswith(b"SCRIPT=route.txt" + NL.encode())
        assert (d / "keep/game-log99.elf").read_bytes() == b"ELF" * 100
        assert "Test request: log99" in (d / "keep/TEST_REQUEST_log99.md").read_text(encoding="utf-8")
        rc, out = quiet(stage_console.main, [str(d / "cfg.json"), "log99", "--set", "SCRIPT=route.txt"])
        assert json.loads(out)["changed_on_card"] == [], "staged again although nothing changed"
        (d / "build/game.elf").write_bytes(b"ELF2" * 100)
        os.utime(d / "build/game.nro")
        try:
            quiet(stage_console.main, [str(d / "cfg.json"), "log99"])
            raise AssertionError("replaced a kept ELF without --force")
        except SystemExit as e:
            assert "other bytes" in str(e), e


if __name__ == "__main__":
    for t in (test_replay_check, test_widen, test_stage):
        t()
        print(f"{t.__name__}: ok")
