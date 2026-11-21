"""Turn PGO count streams from an instrumented Switch build into .gcda files for the -fprofile-use build.

The instrumented build streams every object's counters with __gcov_info_to_gcda() (tools/pgo_stream.c). A stream holds,
per object, a "gcfn" record with the .gcda name the instrumented build computed, then that object's .gcda data.

    python tools/pgo_merge.py <folder with .stream files> --profile-dir <dir> [--gcov-tool PATH | --docker-image IMG
                              --mount-host DIR --mount-container DIR] [--rename OLD_PREFIX=NEW_PREFIX]

1. --rename rewrites the start of every .gcda name in a copy of each stream. Use it when the use build lives at another
   path, or when names get too long (Windows tools stop at 259 characters).
2. Runs `gcov-tool merge-stream` on each stream, locally or inside the toolchain's Docker image (--docker-image, with
   the folder holding the streams and the profile dir mounted). Streams are added together: start from an empty
   profile dir, or the counts double.
3. Fixes each .gcda's object summary: the stream path leaves runs = 0 and sum_max = 0, and GCC derives its hot
   threshold from sum_max (with 0, every block counts as hot). They become runs = number of streams and sum_max = the
   largest arc count of all objects.

The counts come from the game's code: keep them out of any public repository.
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

GCDA_MAGIC = 0x67636461            # "gcda"
GCFN_MAGIC = 0x6763666E            # "gcfn": a file name record in a stream
TAG_OBJECT_SUMMARY = 0xA1000000
TAG_ARC_COUNTERS = 0x01A10000


def read_u32(data, pos):
    return struct.unpack_from("<I", data, pos)[0]


def gcfn_at(data, p, version):
    """The name of a gcfn record at p, or None: magic, the stream's version, a length, a NUL-ended .gcda name, then
    the object's gcda data."""
    if p + 12 > len(data) or read_u32(data, p) != GCFN_MAGIC or data[p + 4:p + 8] != version:
        return None
    n = read_u32(data, p + 8)
    raw = data[p + 12:p + 12 + n]
    if n < 6 or len(raw) != n or not raw.endswith(b".gcda\0") or p + 16 + n > len(data) \
            or read_u32(data, p + 12 + n) != GCDA_MAGIC:
        return None
    return raw[:-1].decode()


def split_stream(data):
    """(name, gcda bytes) per object. Each object's data runs to the next real gcfn record."""
    version = data[4:8]
    magic = struct.pack("<I", GCFN_MAGIC)
    marks, p = [], data.find(magic)
    while p >= 0:
        name = gcfn_at(data, p, version)
        if name is not None:
            marks.append((p, name))
        p = data.find(magic, p + 1)
    if not marks or marks[0][0] != 0:
        raise ValueError("the stream does not start with a gcfn record")
    for i, (p, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(data)
        yield name, data[p + 12 + len(name) + 1:end]


def rename_stream(src, dst, old, new):
    data = src.read_bytes()
    version = data[4:8]
    parts, objects, longest = [], 0, 0
    for name, gcda in split_stream(data):
        if name.startswith(old):
            name = new + name[len(old):]
        raw = name.encode() + b"\0"
        longest = max(longest, len(raw) - 1)
        parts += [struct.pack("<I", GCFN_MAGIC), version, struct.pack("<I", len(raw)), raw, gcda]
        objects += 1
    dst.write_bytes(b"".join(parts))
    return objects, longest


def records(data):
    """(tag, payload offset, payload length) of a .gcda (GCC 12+: lengths in bytes; an all-zero block has a negative
    length and no payload)."""
    pos = 16
    while pos + 8 <= len(data):
        tag, length = struct.unpack_from("<Ii", data, pos)
        if tag == 0:
            return
        size = max(length, 0)
        yield tag, pos + 8, size
        pos += 8 + size


def max_arc_count(path):
    data = path.read_bytes()
    best = 0
    for tag, at, size in records(data):
        if tag == TAG_ARC_COUNTERS and size:
            best = max(best, max(struct.unpack_from(f"<{size // 8}q", data, at)))
    return best


def fix_summary(path, runs, sum_max):
    data = bytearray(path.read_bytes())
    if len(data) < 16 or read_u32(data, 0) != GCDA_MAGIC:
        return "not a gcda"
    for tag, at, size in records(data):
        if tag == TAG_OBJECT_SUMMARY:
            old_runs, old_max = struct.unpack_from("<II", data, at)
            if old_runs == 0 and old_max == 0:
                struct.pack_into("<II", data, at, runs, min(sum_max, 0xFFFFFFFF))
                path.write_bytes(bytes(data))
                return "summary set"
            return "summary kept"
    return "no object summary"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("streams", type=Path)
    ap.add_argument("--profile-dir", type=Path, required=True, help="where the .gcda files land (host path)")
    ap.add_argument("--work", type=Path, help="folder for the stream copies (default: <profile-dir>/../pgo-streams)")
    ap.add_argument("--gcov-tool", default="aarch64-none-elf-gcov-tool")
    ap.add_argument("--docker-image", help="run gcov-tool in this image (e.g. the pinned devkitA64 digest)")
    ap.add_argument("--mount-host", type=Path, help="host folder mounted for --docker-image; must hold the work "
                                                     "folder and match the build's paths")
    ap.add_argument("--mount-container", help="where --mount-host appears in the container (e.g. /repo)")
    ap.add_argument("--rename", help="OLD_PREFIX=NEW_PREFIX for every .gcda name in the streams")
    a = ap.parse_args()

    streams = sorted(a.streams.glob("*.stream"))
    if not streams:
        sys.exit(f"no .stream files in {a.streams}")
    a.profile_dir.mkdir(parents=True, exist_ok=True)   # merge-stream skips every object when it is missing
    work = a.work or a.profile_dir.parent / "pgo-streams"
    work.mkdir(parents=True, exist_ok=True)
    for s in streams:
        if a.rename:
            old, new = a.rename.split("=", 1)
            objects, longest = rename_stream(s, work / s.name, old, new)
            print(f"{s.name}: {objects} objects, longest name {longest} characters")
            if longest > 259:
                print("  warning: names over 259 characters are not written by Windows tools")
        else:
            shutil.copyfile(s, work / s.name)
            print(f"{s.name}: {s.stat().st_size / 1048576:.1f} MB")

    if a.docker_image:
        if not a.mount_host or not a.mount_container:
            sys.exit("--docker-image needs --mount-host and --mount-container")
        host, cont = a.mount_host.resolve(), a.mount_container
        rel = work.resolve().relative_to(host).as_posix()
        script = (f"set -e; for s in {cont}/{rel}/*.stream; do /opt/devkitpro/devkitA64/bin/{a.gcov_tool} "
                  f"merge-stream \"$s\"; echo \"merged $(basename $s)\"; done")
        cmd = ["docker", "run", "--rm", "--network", "none", "--mount",
               f"type=bind,src={host.as_posix()},dst={cont}", a.docker_image, "bash", "-c", script]
        r = subprocess.run(cmd, env=dict(os.environ, MSYS_NO_PATHCONV="1"))
        if r.returncode:
            sys.exit("merge-stream failed")
    else:
        for s in sorted(work.glob("*.stream")):
            if subprocess.run([a.gcov_tool, "merge-stream", str(s)]).returncode:
                sys.exit(f"merge-stream failed on {s.name}")

    gcdas = sorted(a.profile_dir.rglob("*.gcda"))
    if not gcdas:
        sys.exit(f"no .gcda files appeared in {a.profile_dir}: the names in the streams point elsewhere (--rename)")
    sum_max = max(max_arc_count(g) for g in gcdas)
    results = {}
    for g in gcdas:
        results.setdefault(fix_summary(g, len(streams), sum_max), []).append(g.name)
    print(f"{len(gcdas)} .gcda files in {a.profile_dir}; largest arc count {sum_max}")
    for k, v in results.items():
        print(f"  {k}: {len(v)}")


if __name__ == "__main__":
    main()
