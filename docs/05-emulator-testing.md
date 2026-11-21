# Emulator testing

Both ports test in **Ryubing 1.3.3** (a Ryujinx fork), headless, with the pad driven by a script. It catches hangs, new errors and image regressions between two builds, several times a day, without a console. It does not measure speed (guide 01).

## Running headless

```
Ryujinx.exe --no-gui --disable-docked-mode --skip-user-profiles-manager --ignore-controller-applet
            --ignore-missing-services --graphics-backend OpenGl --vsync-mode Unbounded --input-id-1 0 <game.nro>
```

- Use a **portable** copy (a `portable/` folder beside the executable), or Ryujinx uses `%APPDATA%` and mixes with another install.
- Firmware and keys come from your own console. Never download them.
- The game's log shows up in the Ryujinx log (`svcOutputDebugString`). Better still: the game writes its own log on the emulated card.
- `appletRestartProgram` fails in Ryubing (rc 19289): the game cannot restart itself.
- `--input-id-1 0` (keyboard) gives player 1 a controller. The script replaces its input.

## Scripted pad

The port reads a button script (steps `<ms>:<button>[+<button>][:<hold>]`) from an environment variable and plays by itself. Together with an auto exit after N seconds, a run needs nobody around. The same script and the same NRO work in the emulator and on the console.

LEGO also records what a tester plays and converts it into a script (`padrec_to_script.py`), and has a `speed max` step that lifts the frame limiter outside the menus.

## The runner (`tools/ryubing_run.py`)

1. Links the game folder into the emulated card with a junction (never copies it).
2. Writes the port's settings file with the script, the auto exit and the log path.
3. Starts Ryubing and follows the logs.
4. Stops at the exit marker, on a crash, if the emulator closes, or at the time limit.
5. Writes `summary.json` with the result, the median FPS (all and heavy scenes only), counts per error kind, the levels loaded and per-level statistics.
6. With `--baseline`, compares with an earlier run and flags: a worse result, a new error kind, a level no longer reached, and an FPS drop (diagnostic only).

Error kinds are regular expressions over the game's log. Count **new events**, not lines: in Manhunt, the audio line repeated the running total of underruns, and the right count came from the `(+N)` field. Emulator lines that say nothing about the port (time zone, window focus) go in a noise list.

## Test tiers (Manhunt)

| Tier | Length | Covers |
|---|---|---|
| Smoke | ~4 min | Boot to the first mission, new save |
| One level | ~4 min | Restores the save leading into a level and plays only that level |
| Many levels | ~20 min | 12 levels in a row through the debug menu |

The long test does not need to be the default: the one-level test, on one of the heaviest levels, covers a lot.

### Skipping levels through the game's debug menu

Manhunt has Rockstar's debug menu (L3+R3) with "Complete level". A 296-step script completes the level, waits for the load, plays a little and repeats: 12 levels in 20 minutes. Details that matter:
- the menu remembers the cursor between openings, so the script counts from a fixed point (here, 13 up from the bottom);
- if the game has cheats or a debug menu, look for them before writing long scripts.

### Marking the level in the log

The port prints `[MH-LEVEL] <folder>` the first time it opens a file under a new level folder. The runner splits FPS, draws and vertices per level, which finds the heaviest level (in Manhunt, zoo: 940 draws per frame median, 1,204 at the 90th percentile).

LEGO does the same with a per-frame `[LEVEL]` marker.

### One save per level

During the long run, the runner copies the save folder the moment each level starts loading (`--save-snapshots`). Later, `--level <name>` restores that save and plays only that level. Two cautions:
- **Leave out partition images.** The first snapshots were 49 GB, because they carried the Xbox disk images (`Partition*.img`) that the port rebuilds at boot.
- **Keep only the newest save.** With several saves, the game loaded an older one of its own choosing.

## "Is it the same game?" (LEGO)

With a fixed frame time (`--fixed-dt`), replaying a script is deterministic. LEGO's runner (`emu_test.py`) counts game frames between the script's state changes (a door, a cutscene). Those numbers do not change between runs (hub 796, heavy level 4,252), give or take 1–2 frames. More than 3 off means the build did not play the same game.

It also compares the **work per level** (draws, vertices, shader bytes) with a baseline and marks fields that moved more than 5 %. That informs but does not fail the run: an optimization is meant to change the work. To check the measure detects anything, switching off two state filters on purpose raised shader bytes by 191 % in the heavy level, and nothing else moved past 5 %.

Other LEGO details:
- **Boot failures:** the emulator sometimes exits or hangs before the first level (5 of ~30 runs, with any build). Such a run is retried up to N times.
- **First session (`--cold`):** moves the shader caches off the emulated card for the run and puts them back after. Good for first-time stutters, not for comparing work (two cold runs of the same build differed by up to 24 %).
- **Hangs:** with the game stalled, a GDB dump shows each thread's stack.

## Images: Ryubing cuts every readback to 1/4 (Manhunt and LEGO)

Every readback of an image of width W (`glReadPixels`) returns only W/4 pixels per row in Ryubing. In Manhunt, captures came out with 1/4 of the picture; in LEGO, the emulator's captures had picture only up to column 319 of 1280.

**Workaround** (`tools/gl_readback_wide.c`): blit the frame into a target four times as wide, read the whole target, and compact the rows. On the console the result is the same as a direct read. Keep it behind a switch (`RECOMP_GL_DUMP_READ=wide` in Manhunt).

With whole frames, the runner keeps each capture's mean luminance to compare across builds (black screen, picture too dark).
