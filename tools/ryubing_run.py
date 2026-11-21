"""Run a Switch homebrew NRO in Ryubing (a Ryujinx fork) headless, with a scripted pad, and report how the run went.

Diagnostic only: an emulator says nothing about console speed. Use it for crashes, hangs, new error kinds, levels no
longer reached and image regressions between two builds.

    python tools/ryubing_run.py <port.json> --emu <portable Ryujinx.exe> --nro <game.nro> [--game <your game folder>]
           [--script route.pad] [--secs 240] [--baseline <earlier summary.json>] [--save-snapshots DIR] [--level NAME]

The port config (see examples/ryubing_xboxrecomp.json) names the port's own conventions:
    sd_app          folder on the card, e.g. "switch/mygame"
    env_file        the port's settings file inside it; written for the run, the user's copy restored afterwards
    base_env        settings lines for every emulator run (the release settings plus the periodic perf report)
    log_var, exit_var, script_var    the port's variables for its log file, its auto exit and its pad script
    game_link, game_check            where the game data is linked on the card, and a file that must be in it
    save_dir        the port's save folder on the card (for --reset-save, --save-snapshots, --load-save)
    snapshot_ignore glob patterns left out of save snapshots (e.g. disk images rebuilt at boot)
    keep_newest     {"parent_glob": ..., "file_glob": ...}: in each parent, keep only the newest save slot
    markers         {"exit": ..., "auto_exit": ..., "crash": [...], "level": ...}: strings in the guest log
    perf_regex      regex with named groups (fps, draws, verts at least) over the guest log's perf line
    heavy           {"field": "verts", "min": 20000}: samples counted as gameplay
    errors          {kind: regex}: counted per run and compared with --baseline (count new events, not repeated totals)
    emu_noise       substrings of emulator error lines that say nothing about the port
    max_steps       the port's pad-script step limit

Exit status: 0 when the run reached its auto exit without a crash (and no regression against --baseline), 1
otherwise, 3 for a setup error.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

# Ryubing 1.3.3 headless: no profile picker, missing services answered instead of stopping, OpenGL, no vsync.
# --input-id-1 0 (keyboard) gives player 1 a controller; the pad script replaces its input.
EMU_ARGS = ["--no-gui", "--disable-docked-mode", "--skip-user-profiles-manager", "--ignore-controller-applet",
            "--ignore-missing-services", "--graphics-backend", "OpenGl", "--vsync-mode", "Unbounded",
            "--input-id-1", "0"]
EMU_ERROR = re.compile(r"\|E\||\|C\|")   # Ryujinx error / critical lines
EMU_CRASH = ("Unhandled exception", "Guest stack trace", "InvalidMemoryRegionException")


def fail(msg):
    print("ryubing_run: setup:", msg, file=sys.stderr)
    sys.exit(3)


def read_script(path, max_steps):
    """One step per line (<ms>:<button>[+<button>][:<hold_ms>]), # comments; returns the comma-joined value."""
    steps = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            if not re.fullmatch(r"\d+:[a-z0-9+]+(:\d+)?", line):
                fail(f"{path}: bad step '{line}'")
            steps.append(line)
    if len(steps) > max_steps:
        fail(f"{path}: {len(steps)} steps, the port takes {max_steps}")
    return ",".join(steps)


def link_game(sd_app, game, link, check):
    """<card>/<sd_app>/<link> -> the user's game folder, as a junction or symlink. Never copies, never deletes data."""
    dst = sd_app / link
    if game is None:
        if not (dst / check).exists():
            fail(f"no game data: pass --game <your folder with {check}>")
        return
    game = Path(game).resolve()
    if not (game / check).exists():
        fail(f"{game} has no {check}")
    if dst.exists() or os.path.islink(dst):
        is_link = os.path.isjunction(dst) if hasattr(os.path, "isjunction") else dst.is_symlink()
        if not is_link:
            print(f"note: {dst} is a real folder; using it, --game ignored")
            return
        os.rmdir(dst) if os.name == "nt" else dst.unlink()     # removes the link only
    if os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(game)], capture_output=True, text=True)
        if r.returncode:
            fail(f"mklink /J failed: {r.stdout}{r.stderr}")
    else:
        dst.symlink_to(game, target_is_directory=True)


def take_snapshot(save, dest, cfg):
    shutil.copytree(save, dest, ignore=shutil.ignore_patterns(*cfg.get("snapshot_ignore", [])))
    keep = cfg.get("keep_newest")
    if keep:   # with several saves the title may load an older one of its own choosing
        for parent in Path(dest).glob(keep["parent_glob"]):
            slots = [d for d in parent.iterdir() if d.is_dir() and any(d.glob(keep["file_glob"]))]
            newest = lambda d: max(f.stat().st_mtime for f in d.glob(keep["file_glob"]))
            for old in sorted(slots, key=newest)[:-1]:
                shutil.rmtree(old)


def summarize(guest, emu, cfg):
    perf_rx = re.compile(cfg["perf_regex"])
    level = cfg["markers"].get("level")
    hf, hmin = cfg["heavy"]["field"], cfg["heavy"]["min"]
    rows, per, cur = [], {}, "boot"
    for line in guest:
        if level and level in line:
            cur = line.split(level, 1)[1].strip()
        m = perf_rx.search(line)
        if m:
            r = {k: float(v) for k, v in m.groupdict().items() if v is not None}
            rows.append(r)
            per.setdefault(cur, []).append(r)
    med = lambda xs: round(statistics.median(xs), 1) if xs else None
    heavy = [r["fps"] for r in rows if r.get(hf, 0) > hmin]
    emu_err = [l.strip() for l in emu if EMU_ERROR.search(l) and not any(n in l for n in cfg.get("emu_noise", []))]
    kinds = sorted({re.sub(r"^\S+ \|[EC]\| ", "", re.sub(r"0x[0-9a-fA-F]+|\d+", "#", l))[:160] for l in emu_err})
    return {
        "perf_samples": len(rows),
        "fps_median_all": med([r["fps"] for r in rows]),
        "fps_median_heavy": med(heavy),
        "heavy_samples": len(heavy),
        "errors": {k: sum(1 for l in guest if re.search(p, l, re.I)) for k, p in cfg.get("errors", {}).items()},
        "emu_error_lines": len(emu_err),
        "emu_error_kinds": kinds[:40],
        "levels": [l.split(level, 1)[1].strip() for l in guest if level and level in l],
        "per_level": {lv: {"samples": len(rs), "fps": med([r["fps"] for r in rs]),
                           **{k: med([r[k] for r in rs if k in r]) for k in ("draws", "verts")}}
                      for lv, rs in per.items()},
    }


def compare(cur, base, fps_tol):
    """Regressions of cur against base. FPS changes are reported as a hint, never as proof."""
    out = []
    if base.get("result") == "auto-exit" and cur.get("result") != "auto-exit":
        out.append(f"result {base.get('result')} -> {cur.get('result')}")
    for k, v in cur["errors"].items():
        if v and not base["errors"].get(k):
            out.append(f"new error kind {k} ({v} lines)")
    for k in sorted(set(cur["emu_error_kinds"]) - set(base.get("emu_error_kinds", [])))[:10]:
        out.append(f"new emulator error: {k}")
    lost = [lv for lv in base.get("levels", []) if lv not in cur.get("levels", [])]
    if lost:
        out.append(f"levels reached by the baseline but not now: {', '.join(lost)}")
    a, b = base.get("fps_median_heavy"), cur.get("fps_median_heavy")
    if a and b and b < a * (1 - fps_tol):
        out.append(f"heavy FPS {a} -> {b} (emulator, a hint only)")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config", help="the port's JSON config")
    ap.add_argument("--emu", required=True, help="Ryujinx.exe of a portable copy (portable/ beside it)")
    ap.add_argument("--nro", required=True)
    ap.add_argument("--game", help="your own game folder (linked, never copied)")
    ap.add_argument("--script", help="pad script file")
    ap.add_argument("--secs", type=int, default=240, help="the port's auto exit (default 240)")
    ap.add_argument("--grace", type=int, default=120, help="extra seconds before the run counts as hung")
    ap.add_argument("--env", action="append", default=[], help="extra KEY=VALUE settings line (repeatable)")
    ap.add_argument("--reset-save", action="store_true", help="empty the emulated card's save folder first")
    ap.add_argument("--save-snapshots", metavar="DIR", help="copy the save folder to DIR/<level> when a level starts")
    ap.add_argument("--load-save", metavar="DIR", help="replace the save folder with DIR before the run")
    ap.add_argument("--level", help="play one level from DIR/<level> of --saves-root")
    ap.add_argument("--saves-root", default="saves", help="where --level finds its snapshots (default ./saves)")
    ap.add_argument("--name", help="label for the run folder")
    ap.add_argument("--out", default="emu-runs")
    ap.add_argument("--baseline", help="summary.json of an earlier run")
    ap.add_argument("--fps-tol", type=float, default=0.15)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    m = cfg["markers"]
    emu, nro = Path(args.emu).resolve(), Path(args.nro).resolve()
    if not emu.exists():
        fail(f"no emulator at {emu}")
    if not (emu.parent / "portable").is_dir():
        fail(f"{emu.parent / 'portable'} missing: without it Ryujinx uses %APPDATA% instead of its own folder")
    if not nro.exists():
        fail(f"no NRO at {nro}")
    sd_app = emu.parent / "portable/sdcard" / cfg["sd_app"]
    sd_app.mkdir(parents=True, exist_ok=True)
    link_game(sd_app, args.game, cfg.get("game_link", "game"), cfg["game_check"])
    save = sd_app / cfg.get("save_dir", "save")
    if args.level:
        args.load_save = args.load_save or str(Path(args.saves_root) / args.level)
        args.name = args.name or f"level-{args.level}"
    if args.reset_save and save.is_dir():
        shutil.rmtree(save)                       # the emulator copy's own card only
    if args.load_save:
        if not Path(args.load_save).is_dir():
            fail(f"no save snapshot {args.load_save}")
        shutil.rmtree(save, ignore_errors=True)
        shutil.copytree(args.load_save, save)

    log_name = "emu-run.log"
    lines = list(cfg.get("base_env", [])) + [f"{cfg['log_var']}=sdmc:/{cfg['sd_app']}/{log_name}",
                                             f"{cfg['exit_var']}={args.secs}"]
    if args.script:
        lines.append(f"{cfg['script_var']}=" + read_script(args.script, cfg.get("max_steps", 512)))
    lines += args.env
    env_path, backup = sd_app / cfg["env_file"], sd_app / (cfg["env_file"] + ".emu-backup")
    had_env = env_path.exists()
    if had_env and not backup.exists():
        shutil.copyfile(env_path, backup)
    env_path.write_bytes(("\n".join(lines) + "\n").encode())
    (sd_app / log_name).unlink(missing_ok=True)

    logs_dir = emu.parent / "portable/Logs"
    before = set(logs_dir.glob("*.log")) if logs_dir.is_dir() else set()
    t0, limit = time.time(), args.secs + args.grace
    result, reason, emu_log, pos, exit_seen, emu_lines = "timeout", f"no exit within {limit} s", None, 0, None, []
    proc = subprocess.Popen([str(emu), *EMU_ARGS, str(nro)], cwd=str(emu.parent),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        while time.time() - t0 < limit:
            time.sleep(2)
            if emu_log is None and logs_dir.is_dir():
                new = [p for p in logs_dir.glob("*.log") if p not in before]
                emu_log = max(new, key=lambda p: p.stat().st_mtime) if new else None
            if emu_log is not None:
                with open(emu_log, "rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                cut = chunk.rfind(b"\n") + 1
                pos += cut
                for raw in chunk[:cut].decode("utf-8", "replace").splitlines():
                    emu_lines.append(raw)
                    lv_mark = m.get("level")
                    if args.save_snapshots and lv_mark and lv_mark in raw and save.is_dir():
                        snap = Path(args.save_snapshots) / raw.split(lv_mark, 1)[1].strip()
                        if not snap.exists():           # the first entry into a level is the one to keep
                            take_snapshot(save, snap, cfg)
                            print(f"  save snapshot: {snap.name}")
                    if m["exit"] in raw and exit_seen is None:
                        exit_seen = time.time()
                        result = "auto-exit" if m.get("auto_exit", "auto exit") in raw else "exited"
                        reason = raw.strip()
                    if any(c in raw for c in list(m.get("crash", [])) + list(EMU_CRASH)):
                        result, reason = "crash", raw.strip()
            if result == "crash" or (exit_seen and time.time() - exit_seen > 8):
                break
            if proc.poll() is not None:
                if result == "timeout":
                    result, reason = "emulator-exited", f"Ryujinx exited with {proc.returncode}"
                break
    finally:
        if proc.poll() is None:                   # only the process this run started
            proc.terminate()
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
        if had_env:
            shutil.copyfile(backup, env_path)
            backup.unlink()
        else:
            env_path.unlink(missing_ok=True)

    name = args.name or (Path(args.script).stem if args.script else "noscript")
    dest = Path(args.out) / f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{name}-{result}"
    dest.mkdir(parents=True)
    guest = []
    if (sd_app / log_name).exists():
        shutil.copyfile(sd_app / log_name, dest / "guest.log")
        guest = (dest / "guest.log").read_text("utf-8", "replace").splitlines()
    if emu_log is not None:
        shutil.copyfile(emu_log, dest / "ryujinx.log")
    if not guest:   # the port's log never opened: use the guest lines in the emulator log
        guest = emu_lines
    summary = {"result": result, "reason": reason, "seconds": round(time.time() - t0), "nro": nro.name,
               "nro_size": nro.stat().st_size, "script": args.script, "env": lines, **summarize(guest, emu_lines, cfg)}
    regressions = []
    if args.baseline:
        regressions = compare(summary, json.loads(Path(args.baseline).read_text(encoding="utf-8")), args.fps_tol)
        summary["baseline"], summary["regressions"] = args.baseline, regressions
    (dest / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

    print(f"\nresult: {result}: {reason}")
    print(f"FPS (emulator, diagnostic): median {summary['fps_median_all']} over {summary['perf_samples']} samples, "
          f"{summary['fps_median_heavy']} over {summary['heavy_samples']} heavy samples")
    if summary["levels"]:
        print("levels:", " -> ".join(summary["levels"]))
    print("errors:", ", ".join(f"{k} {v}" for k, v in summary["errors"].items() if v) or "none",
          f"| emulator error lines {summary['emu_error_lines']}")
    for r in regressions:
        print("REGRESSION:", r)
    print("run folder:", dest)
    return 0 if result == "auto-exit" and not regressions else 1


if __name__ == "__main__":
    sys.exit(main())
