"""Did a scripted run replay the same game, and did it do more or less work? Reads a guest log and compares with a baseline.

From LEGO's emu_test.py. With a fixed frame time and a scripted pad, a replay is deterministic, so the number of guest
frames between two state changes of the game (a door, a cutscene: whatever your script re-anchors on) is the same in
every run of a good build, give or take a frame or two. A build that did not play the same game is off by hundreds of
frames or misses a level. Next to that it averages "work" counters per level (draws, vertices, shader bytes: counts that
are the same on any host) and flags fields that moved more than the noise. Work changes inform, they do not fail the
run: an optimization is meant to change the work.

    python tools/replay_check.py <config.json> <guest log or run folder> [--baseline B.json] [--save-baseline B.json]
    python tools/replay_check.py <config.json> --run "<runner command>" --log <log the runner writes> [--boot-retries 2] ...

--run starts the run itself (for example tools/ryubing_run.py ...) and runs it again, up to --boot-retries times, when
the log has no level marker: an emulator boot failure says nothing about the build (LEGO: 5 of about 30 runs).

Config (see examples/replay_check.json); every regex is matched against one log line:
    level      regex, groups (name)(frame): the port's level marker; it resets the anchors
    anchor     regex, groups (where)(state)(frame): a line printed when the script re-anchors on a state change
    done       regex: the script finished
    failed     regex, optional group (step): the script failed
    crash      list of regexes: crash lines
    work       {"regex": ..., "fields": [names], "replays_group": name or null, "light": {"field": f, "below": n}}:
               a line with named numeric groups, averaged per level (weighted by replays_group when given); windows
               whose field is below n (menus, loads) go under "<level> (light)" and are not compared
    noise      percent beyond which a work field is flagged (default 5)
    field_noise  {field: percent}: wider noise for fields that move more between two runs of one build
    gap_tolerance  frames (default 3)
Measure the noise first: two runs of one build (A/A). In LEGO they differed by under 3 % in the heaviest level, up to
5 % in the hub, 11 % for hub vertices; the frame gaps by 1-2 frames.

What it cannot tell: speed on the console. Exit status 0 = finished, no crash, same game as the baseline; 1 otherwise.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def read_log(path):
    p = Path(path)
    if p.is_dir():
        logs = sorted(p.glob("*.log"), key=lambda f: f.stat().st_size, reverse=True)
        if not logs:
            sys.exit(f"no .log file in {p}")
        p = logs[0]
    return p.read_bytes().decode("utf-8", "replace").splitlines()


def summarize(lines, cfg):
    level = re.compile(cfg["level"])
    anchor = re.compile(cfg["anchor"]) if cfg.get("anchor") else None
    done = re.compile(cfg.get("done", r"^$^"))
    failed = re.compile(cfg.get("failed", r"^$^"))
    crash = [re.compile(c) for c in cfg.get("crash", [])]
    wc = cfg.get("work") or {}
    work_re = re.compile(wc["regex"]) if wc.get("regex") else None
    fields = wc.get("fields", [])
    light = wc.get("light")

    levels, gaps, crash_lines, result = [], [], [], "unknown"
    sums = {}
    cur_level, held = "?", None
    for line in lines:
        m = level.search(line)
        if m:
            cur_level = m.group(1)
            levels.append([cur_level, int(m.group(2))])
            held = None   # a span across a level change includes a load, whose length is real time
            continue
        if anchor:
            m = anchor.search(line)
            if m:
                where, state, frame = m.group(1), m.group(2), int(m.group(3))
                if held and held[0] == where:
                    gaps.append(f"{where} {held[1]}: {frame - held[2]} frames")
                held = (where, state, frame)
                continue
        if done.search(line):
            result = "done"
        m = failed.search(line)
        if m:
            result = "failed" + (": " + m.group(1) if m.groups() and m.group(1) else "")
        if any(c.search(line) for c in crash):
            crash_lines.append(line.strip())
        if work_re:
            m = work_re.search(line)
            if m:
                vals = {f: float(m.group(f)) for f in fields}
                n = int(m.group(wc["replays_group"])) if wc.get("replays_group") else 1
                key = cur_level
                if light and vals.get(light["field"], 0) < light["below"]:
                    key += " (light)"
                s = sums.setdefault(key, {f: 0.0 for f in fields} | {"replays": 0})
                for f in fields:
                    s[f] += vals[f] * n
                s["replays"] += n
    work = {k: {"replays": s["replays"], **{f: s[f] / s["replays"] for f in fields}} for k, s in sums.items() if s["replays"]}
    return {"result": result, "crash": crash_lines[:5], "levels": levels, "gaps": gaps, "work": work}


GAP = re.compile(r"^(.+): (-?\d+) frames$")


def same_game(gaps, base_gaps, tolerance):
    """The state change may be noticed a frame or two later in one run than in another (LEGO: the hub's 796 read 797
    once). More than the tolerance, or a different list, means the build did not replay the same game."""
    if len(gaps) != len(base_gaps):
        return False
    for a, b in zip(gaps, base_gaps):
        ma, mb = GAP.match(a), GAP.match(b)
        if not ma or not mb or ma.group(1) != mb.group(1) or abs(int(ma.group(2)) - int(mb.group(2))) > tolerance:
            return False
    return True


def report(cur, base, cfg, out=print):
    noise = cfg.get("noise", 5.0)
    field_noise = cfg.get("field_noise", {})
    tol = cfg.get("gap_tolerance", 3)
    fields = (cfg.get("work") or {}).get("fields", [])
    ok = cur["result"] == "done" and not cur["crash"]
    moved = []
    out(f"result: {cur['result']}" + (f"; crash lines: {cur['crash']}" if cur["crash"] else ""))
    out("frames between state changes: " + ("; ".join(cur["gaps"]) or "none"))
    if base:
        same = same_game(cur["gaps"], base["gaps"], tol)
        out(f"  baseline: {'; '.join(base['gaps']) or 'none'} -> "
            + (f"same game (within {tol} frames)" if same else "DIFFERENT (the run did not replay the same game)"))
        ok = ok and same
    for lv in sorted(cur["work"]):
        if lv.endswith("(light)"):
            continue
        w, b = cur["work"][lv], (base or {}).get("work", {}).get(lv)
        cells = []
        for f in fields:
            if b and b.get(f):
                d = (w[f] - b[f]) / b[f] * 100
                flag = abs(d) > max(noise, field_noise.get(f, 0))
                if flag:
                    moved.append(f"{lv} {f} {d:+.0f} %")
                cells.append(f"{f} {w[f]:.1f} ({d:+.1f} %{' <-' if flag else ''})")
            else:
                cells.append(f"{f} {w[f]:.1f}")
        out(f"  {lv} ({w['replays']} replays): " + ", ".join(cells))
    out("VERDICT: " + ("OK" if ok else "CHECK") + (f"; work changed: {', '.join(moved)}" if moved else ""))
    return ok, moved


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config")
    ap.add_argument("log", nargs="?", help="guest log, or a run folder (its largest .log)")
    ap.add_argument("--run", help="runner command to start the run (quoted, run through the shell)")
    ap.add_argument("--log", dest="run_log", help="with --run: the log the runner writes")
    ap.add_argument("--boot-retries", type=int, default=2)
    ap.add_argument("--baseline")
    ap.add_argument("--save-baseline")
    args = ap.parse_args(argv)
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))

    if args.run:
        if not args.run_log:
            sys.exit("--run needs --log")
        level = re.compile(cfg["level"])
        for attempt in range(args.boot_retries + 1):
            subprocess.run(args.run, shell=True)
            lines = read_log(args.run_log) if Path(args.run_log).exists() else []
            if any(level.search(l) for l in lines):
                break
            if attempt < args.boot_retries:
                print(f"no level marker: emulator boot failure, running again ({attempt + 1} of {args.boot_retries})")
    elif args.log:
        lines = read_log(args.log)
    else:
        sys.exit("give a log, or --run with --log")

    cur = summarize(lines, cfg)
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8")) if args.baseline else None
    ok, _ = report(cur, base, cfg)
    if args.save_baseline:
        if cur["result"] != "done":
            print("not saved as a baseline: the run did not finish")
        else:
            Path(args.save_baseline).write_text(json.dumps(cur, indent=1), encoding="utf-8")
            print(f"baseline saved: {args.save_baseline}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
