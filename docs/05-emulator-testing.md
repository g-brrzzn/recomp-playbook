# Emulator testing

Every port tests in **Ryubing 1.3.3** (a Ryujinx fork), headless, with the pad driven by a script. It catches hangs, new errors and image regressions between two builds, several times a day, without a console. It does not measure frame rate or GPU time; CPU work only in a narrow way (guide 01).

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

### Scripts that wait for the game (RTCW)

A timed script presses buttons at fixed moments. In RTCW the timed scripts broke the day the menus became 16:9: the button they clicked by moving the cursor for a fixed time had moved. The port's command script has steps that wait instead:
- `@waitlevel`: until a map has loaded since the last command and its first menu has the input;
- `@waitgame`: until no menu, console or cutscene has the input;
- `@cursor dx dy`: moves the menu cursor in the menu's own units, so `@cursor -2000 -2000` then `@cursor 600 450` lands on one spot whatever the screen;
- `@skipcam`: presses enter while a cutscene runs.

The same script runs in the emulator and on the console, whose loads are two or three times longer.

Long scripted runs (RTCW):
- **Make the player safe.** A death in the middle of `levels` made the engine reload the map, and the next map command was dropped while it did: the run skipped the last maps. God mode and no-target after each map's start.
- **Put back what the test changes.** A test that rebinds a control (to check the controls page) ends by binding it back; settings files persist between runs.
- **The runner's time limit must exceed the game's auto exit**, or a run that passed reports a timeout.

Know what each step waits for. `@waitlevel` waits for the pregame screen; a loaded savegame has none, and loading a save of the map one is on gives no new level at all: the script waited until its time ran out. Load a save with `@waitgame` (its time is the load's), and from another map.

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

## Shorter runs that answer the same thing (RTCW)

- **A console session, checked in the emulator first, with short states.** The script generator writes the console's session and a copy whose states last 2-3 s instead of 10-12. The copy only has to show the session goes through to its end (every state, every restart, no error): 6 minutes instead of 21. What remains are the map loads and video restarts.
- **The emulator benchmark:** two maps instead of three (the third showed nothing the other two did not), 8 s standing still each instead of 15: 72 s a run instead of 3.5 minutes, at about 10 % noise instead of 6 %. For a difference under ~10 %, two short runs still cost less than one long run. `tools/ab_compare.py --by` compares two such runs map by map.

## "Is it the same game?" (LEGO)

With a fixed frame time (`--fixed-dt`), replaying a script is deterministic. LEGO's runner (`emu_test.py`; generic version `tools/replay_check.py`, which reads any runner's log) counts game frames between the script's state changes (a door, a cutscene). Those numbers do not change between runs (hub 796, heavy level 4,252), give or take 1–2 frames. More than 3 off means the build did not play the same game.

It also compares the **work per level** (draws, vertices, shader bytes) with a baseline and marks fields that moved more than 5 %. That informs but does not fail the run: an optimization is meant to change the work. To check the measure detects anything, switching off two state filters on purpose raised shader bytes by 191 % in the heavy level, and nothing else moved past 5 %.

Other LEGO details:
- **Boot failures:** the emulator sometimes exits or hangs before the first level (5 of ~30 runs, with any build). Such a run is retried up to N times.
- **First session (`--cold`):** moves the shader caches off the emulated card for the run and puts them back after. Good for first-time stutters, not for comparing work (two cold runs of the same build differed by up to 24 %).
- **Hangs:** with the game stalled, a GDB dump shows each thread's stack. LEGO's runner takes it by itself when the frame log stops for N seconds (`--gdb-on-stall`); attaching GDB and continuing froze the run, so dump and stop.

## Locating a crash from the Ryujinx log (LEGO)

Read this first, before trying a fix. In LEGO, hours went into fixes built on guesses for a crash whose location was sitting in the log; once read, the next three crashes were each located within a run or two. When the guest touches unmapped memory, the Ryujinx log has, just above the `InvalidAccessHandler: Invalid memory access at virtual address ...` line:
- `PrintGuestStackTrace`: the host call stack as offsets into the NRO (`lswtcs:0x26db50c`);
- `PrintGuestRegisterPrintout`: X0-X28, FP, LR, SP and PC.

How to read it:
- The offsets are addresses in the ELF the NRO was made from: `aarch64-none-elf-addr2line -f -C -i -e game.elf 0x26db50c ...` gives the generated function and line of each frame. Keep the ELF of every build you test.
- The PC is the start of the translated block (the whole function, for the JIT), not the faulting instruction. The LR and the frames say where you are.
- With XenonRecomp's `PPC_FUNC(ctx, base)`: X0 is the guest context, X1 the guest memory base. The faulting address minus the base is the guest address (Ryujinx reports it page-aligned).
- Match the other registers to guest values you know: in LEGO, X9 = 0xE1000 (one 1280×720 Y plane), X6 = the movie's texture and X10 = the D3D device placed the crash in a texture unlock, after a call whose return address was in X2.
- `HLE.GuestThread.N` in the log is the kernel thread id. Log each host thread's id once at creation (`svcGetThreadId`) to know which guest thread crashed.

Then confirm with a probe at the place itself: an override of the function (reached only from callers in other generated files, see guide 07) that checks its inputs and prints them when they are bad. In LEGO that showed the main thread's PCR page full of 0x11 bytes (guide 11). A host thread polling memory from outside missed it: the bad value lived for microseconds.

Count the outcome you care about, not a proxy: "players created" looked fine while every new player was failing at once; "full plays" (the decoder reaching the last frame) told the truth.

## Images: Ryubing cuts every readback to 1/4 (Manhunt and LEGO)

Every readback of an image of width W (`glReadPixels`) returns only W/4 pixels per row in Ryubing. In Manhunt, captures came out with 1/4 of the picture; in LEGO, the emulator's captures had picture only up to column 319 of 1280.

**Workaround** (`tools/gl_readback_wide.c`): blit the frame into a target four times as wide, read the whole target, and compact the rows. On the console the result is the same as a direct read. Keep it behind a switch (`RECOMP_GL_DUMP_READ=wide` in Manhunt).

With whole frames, the runner keeps each capture's mean luminance to compare across builds (black screen, picture too dark).

## An image fault only the emulator may have (RTCW)

After many map loads, Ryubing drew whole surfaces black (10-85 % of the pixels in some views). Hours went into it; on the console the same views were 0.4-3.6 % black (dark rooms). What worked, and what would have saved time:
- **Ask the console first.** Put screenshots of the same views in the next console session (the port saves one per state) before any long hunt. One session settled what a day in the emulator could not.
- **A number, not a look.** A small script gives each capture's share of near-black pixels; compare that across builds.
- **Repeat every run.** The result was bimodal: the same build gave a clean run and a dark one. A theory "confirmed" by one clean run (draw ranges) was a false lead, reverted.
- **Bisect builds, not guesses:** old commits built in a `git worktree` and run with the runner's NRO option. Every build back to the first one showed it.
- **Change the emulator, not the game:** the graphics backend (OpenGL, Vulkan) and the memory mode, then the game's own features (vertex light, fog, clears), and log what the game uploads (texture data was not black). None of them moved it.

## The emulator's file system is not the card's (RTCW)

The emulator reads the PC's disk. A change that cut RTCW's loads in the emulator from 18-30 s to 6-8 s (a larger read buffer, cheap seeks) left the console's unchanged, and what cost on the console (metadata requests for files that do not exist) cost little in the emulator (guide 12). Load times are a console measurement, like frame rate.
