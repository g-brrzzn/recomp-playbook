"""Stage one console test in a single command: the SD files, the kept ELF, a hash manifest and the test request.

From LEGO's stage_run.py. Each console session is precious (guide 06), so staging must never hand the tester an old
build or a half-copied card.

    python tools/stage_console.py <config.json> <label> [--set KEY=VALUE ...] [--play "..."] [--read notes.md] [--force]

Steps, each checked:
  1. The NACP's display version must end with <label>, so an old NRO is never staged by mistake, and the NRO must be
     newer than its ELF (the last build finished packing).
  2. The ELF is kept as <keep_dir>/<name>-<label>.elf: crash offsets in the emulator or console logs are ELF addresses
     (guide 05), so every tested build needs its own. A different file of that name is refused unless --force.
  3. The SD tree: every file in "files" copied to <sd>/<dest>, the settings file written from the profile plus the
     --set lines. Only files whose bytes differ are copied.
  4. Every staged file is hashed again against its source; <keep_dir>/sdcard-manifest-<label>.json lists them, so a
     copied card can be checked later.
  5. <keep_dir>/TEST_REQUEST_<label>.md: the build, the hashes, what to copy (only what changed since the last staging),
     how to play and what the logs will be read for.
Nothing is sent anywhere: the copy and the play stay with the tester.

Config (paths relative to the config file):
    nro, elf, nacp     the build's files
    name               short name for the kept ELF
    sd                 the staging folder that mirrors the card
    keep_dir           where the kept ELF, manifests and requests go (keep it out of the public repo)
    profile            settings file for the console (e.g. the release settings plus the A/B switches)
    profile_dest       its path on the card, e.g. "mygame/env.txt"
    nro_dest           e.g. "switch/mygame/mygame.nro"
    files              [{"src": glob, "dest": folder on the card}]: extra files (pad scripts, ...)
    play               default play instructions
"""
import argparse
import glob
import hashlib
import json
import shutil
import sys
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def nacp_version(nacp):
    """Display version: 16 bytes at 0x3060 of the NACP."""
    return Path(nacp).read_bytes()[0x3060:0x3070].split(b"\0", 1)[0].decode("ascii", "replace")


def put(src, dst, data=None):
    """Copy src (or write data) to dst only when the bytes differ; True if dst changed."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file():
        if data is not None and dst.read_bytes() == data:
            return False
        if data is None and dst.stat().st_size == src.stat().st_size and sha256(dst) == sha256(src):
            return False
    if data is not None:
        dst.write_bytes(data)
    else:
        shutil.copyfile(src, dst)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", type=Path)
    ap.add_argument("label")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="line added to the settings file")
    ap.add_argument("--play")
    ap.add_argument("--read", type=Path)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    here = args.config.resolve().parent

    def path(key):
        return (here / cfg[key]).resolve()

    nro, elf, nacp, profile, sd, keep = (path(k) for k in ("nro", "elf", "nacp", "profile", "sd", "keep_dir"))
    for p in (nro, elf, nacp, profile):
        if not p.is_file():
            sys.exit(f"missing: {p}")
    version = nacp_version(nacp)
    if not version.endswith(args.label):
        sys.exit(f"NACP version is {version!r}, not ...{args.label}: build the right version first")
    if nro.stat().st_mtime < elf.stat().st_mtime:
        sys.exit("the NRO is older than the ELF: the last build did not finish packing")

    keep.mkdir(parents=True, exist_ok=True)
    kept = keep / f"{cfg.get('name', 'game')}-{args.label}.elf"
    if kept.is_file() and sha256(kept) != sha256(elf) and not args.force:
        sys.exit(f"{kept} exists with other bytes (--force replaces it)")
    put(elf, kept)

    env = profile.read_bytes()
    if args.set:
        nl = b"\r\n" if b"\r\n" in env else b"\n"
        env = env.rstrip(b"\r\n") + nl + b"# stage_console.py" + nl + nl.join(s.encode() for s in args.set) + nl
    plan = [(nro, cfg["nro_dest"], None), (profile, cfg["profile_dest"], env)]
    for spec in cfg.get("files", []):
        for src in sorted(glob.glob(str(here / spec["src"]))):
            plan.append((Path(src), f"{spec['dest'].rstrip('/')}/{Path(src).name}", None))

    changed, manifest = [], []
    for src, rel, data in plan:
        dst = sd / rel
        if put(src, dst, data):
            changed.append(rel)
        want = hashlib.sha256(data).hexdigest() if data is not None else sha256(src)
        got = sha256(dst)
        if got != want:
            sys.exit(f"staged {rel} does not match its source")
        manifest.append({"path": rel, "bytes": dst.stat().st_size, "sha256": got})
    man = keep / f"sdcard-manifest-{args.label}.json"
    man.write_text(json.dumps({"label": args.label, "version": version, "files": manifest}, indent=2) + "\n", encoding="utf-8")

    copy = [f"- `{rel}` -> `sdmc:/{rel}`" for rel in changed] or ["- Nothing changed since the last staging: the card is already right."]
    read = args.read.read_text(encoding="utf-8").strip() if args.read else "- (fill in)"
    request = "\n".join([
        f"# Test request: {args.label} (one session)", "",
        f"**Build:** `{version}`, NRO `{sha256(nro)[:8]}`, ELF kept as `{kept.name}` (`{sha256(elf)[:8]}`).", "",
        "## Copy to the card (from the staging folder)", *copy, "", "Do not delete anything on the card.", "",
        "## Play", args.play or cfg.get("play", "- (fill in)"), "", "## What the logs will be read for", read, ""])
    req = keep / f"TEST_REQUEST_{args.label}.md"
    req.write_text(request, encoding="utf-8")
    print(json.dumps({"version": version, "elf_kept": str(kept), "changed_on_card": changed,
                      "manifest": str(man), "request": str(req)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
