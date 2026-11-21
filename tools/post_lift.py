"""Reversible edits of a recompiler's generated C files, applied in place after each lift.

Each edit adds a header after an anchor line (usually the generated file's include) and one line at the top of every
function the function regex matches. Both carry a mark, so the edit can be taken out again; --undo restores the
recompiler's output byte for byte. An environment switch set to 0 leaves an edit out. Only files whose text changes
are rewritten, so an incremental build recompiles only what changed.

    python -I tools/post_lift.py <config.json> <generated dir>           apply the edits (minus switched-off ones)
    python -I tools/post_lift.py <config.json> <generated dir> --undo    restore the recompiler's output

Config (see examples/post_lift_xboxrecomp.json):
    {
      "files": "recomp_[0-9][0-9][0-9][0-9].c",             glob inside the generated dir
      "anchor": "#include \"recomp_funcs.h\"",                 the header goes after this line
      "function": "^(void sub_[0-9A-F]+\\(void\\)\\n\\{\\n)",  regex; group 1 is kept, the local line follows it
      "edits": [
        {"name": "membase", "env": "MY_MEMBASE_LOCAL",
         "header": ["#undef XBOX_PTR", "#define XBOX_PTR(a) ((uintptr_t)(uint32_t)(a) + _plmb)"],
         "local": "const uintptr_t _plmb = (uintptr_t)g_xbox_mem_offset;"}
      ]
    }
Edits are applied in list order and each is undone on its own, so the result does not depend on what the files held
before. Pick local names the recompiler does not use (xboxrecomp already uses _r).
"""
import json
import os
import re
import sys
from pathlib import Path

NL = "\n"


def load(config_path):
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    anchor = cfg["anchor"] + NL
    func = re.compile(cfg["function"], re.M)
    edits = []
    for e in cfg["edits"]:
        mark = f"/* post-lift: {e['name']} */"
        header = mark + NL + "".join(line + NL for line in e["header"])
        local = "    " + e["local"] + " " + mark + NL
        edits.append({"name": e["name"], "env": e.get("env"), "header": header, "local": local})
    return cfg["files"], anchor, func, edits


def apply(text, anchor, func, edit):
    if edit["header"] in text:
        return text
    if anchor not in text:
        raise ValueError("anchor line not found")
    text = text.replace(anchor, anchor + edit["header"], 1)
    return func.sub(lambda m: m.group(1) + edit["local"], text)


def undo(text, edit):
    return text.replace(edit["header"], "").replace(edit["local"], "")


def rewrite(text, anchor, func, edits, wanted):
    for e in edits:
        text = undo(text, e)
    for e in edits:
        if wanted[e["name"]]:
            text = apply(text, anchor, func, e)
    return text


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    pattern, anchor, func, edits = load(argv[1])
    gen = Path(argv[2])
    undo_all = "--undo" in argv[3:]
    wanted = {e["name"]: not undo_all and not (e["env"] and os.environ.get(e["env"]) == "0") for e in edits}
    files = sorted(gen.glob(pattern))
    if not files:
        sys.exit(f"post_lift: no files matching {pattern} in {gen}")
    changed, counts = 0, {e["name"]: 0 for e in edits}
    for f in files:
        old = f.read_text(encoding="utf-8")
        try:
            new = rewrite(old, anchor, func, edits, wanted)
        except ValueError as err:
            sys.exit(f"post_lift: {f.name}: {err}")
        for e in edits:
            counts[e["name"]] += new.count(e["local"])
        if new != old:
            f.write_text(new, encoding="utf-8", newline=NL)
            changed += 1
    state = ", ".join(f"{n} {'on' if wanted[n] else 'off'} ({counts[n]} functions)" for n in counts)
    print(f"post_lift: {state}; {changed} of {len(files)} files rewritten")


if __name__ == "__main__":
    main(sys.argv)
