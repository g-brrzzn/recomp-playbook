# Console testing

Only the console measures speed. The tester's time is the scarcest resource, so each session has to count.

## Hands-off A/B kit (Manhunt)

A folder to copy to the SD card root, with:
- `game-a.nro` and `game-b.nro` (the two builds);
- a test settings file: the normal settings, the perf report every 2 s, the pad script and the auto exit;
- the normal settings kept aside, to go back to playing;
- a step-by-step `README.txt` written for someone non-technical.

The tester opens a, waits for it to return to the menu by itself, opens b, waits again, and sends back both logs. Then, on the PC, `tools/ab_compare.py log-a.txt log-b.txt`.

### One log per build with a single settings file

The log path accepts `{nro}`, replaced by the running NRO's file name:
```
MANHUNT_LOG_FILE=sdmc:/switch/game/log-{nro}.txt
```
The name comes from `argv[0]`. Both builds write separate logs with the same settings.

### What to compare

`ab_compare.py` uses only heavy-scene samples (in Manhunt, over 20,000 vertices per frame) and prints the medians of FPS, game-thread CPU, graphics CPU, audio CPU, GL time per draw and the share of slow frames. Compare the draws per frame too: more draws means a heavier scene, and then the comparison does not hold.

One pair of runs is noisy (the script drifts and scenes change a little). Run a, b, a, b before trusting a difference under ~5 %. Same mode, same charger, same clocks.

## A/B within one session (LEGO)

When a change can be switched during play, one build is enough:
- `LSWTCS_ABSTATES=<state1>,<state2>,...`: the port cycles the states on a fixed period and marks in the log which state each sample belongs to;
- include two identical states (null control). Their difference is the session's noise (guide 01).

## One session, many answers (RTCW)

A session that stands still at a fixed scene and changes one thing at a time answers several questions in one trip. RTCW's fourth session, ~17 minutes, on two maps:
- states with a label in the log (`nx_abLabel`), 10-12 s each: three ways to wait for the GPU before the swap at two resolutions, then each renderer feature off alone (dynamic lights, trilinear filtering, sky, sun, flares, model detail, fog, texture size, detail textures). With the GPU time logged per second, each state gives that feature's GPU cost;
- **a reference state set explicitly** before the feature states: every setting at its known value, not whatever the tester's saved settings hold (the tester's config came from an earlier session and differed from the defaults);
- settings that need a video restart go through the port's own restart command, which sets the Switch's resolution (and the resolution scale under test) before restarting: one restart in and one out;
- **null control:** the reference state again at the end;
- test-only settings are not saved in the player's config, so the game is the same after the test;
- the session is checked in the emulator first in its short form (guide 05).

## Staging the session (LEGO)

`stage_run.py <label>` (generic version: `tools/stage_console.py`) prepares the card and refuses silly mistakes:
- refuses a build whose NACP version does not end with the label, or whose NRO is older than its ELF;
- keeps the ELF aside (to read crash stacks later) and refuses to overwrite a different ELF with the same label;
- checks each copy's SHA-256 and writes a manifest that another script checks on the card;
- writes the test request listing only the files that changed since last time.

## Measuring without FPS

FPS mixes CPU, GPU and scene. Metrics that helped more:
- **CPU per game-function call** (LEGO): stable across sessions (~3 %) and sensitive to generated-code changes.
- **Frames binned by load** (LEGO): compares frame times only between frames with a similar draw count, with a confidence interval.
- **Sampling profiler behind a switch** (LEGO, `LSWTCS_HWPROF=2`; Manhunt, `MANHUNT_CALL_PROFILE`; RTCW, `RTC_PROFILE=2`): shows where the time goes before any change. RTCW's (generic version `tools/sampling_profiler.c`, report `tools/profile_report.py`) adds three things:
  - the call chain follows the frame pointers: build your code with `-fno-omit-frame-pointer`, and since code without them (Mesa, libnx) leaves x29 alone, a sample deep in the driver still names the game function that called it. LEGO's stack scan could only say what was *probably* calling;
  - x29 then points at the frame of the last function that has one, so the frame chain alone skips the driver's own calls and the return into that function. Those are in the stack below the last frame record, which is scanned first, each word checked: the BL before it must go into the function of the frame found before it (a BLR is kept once a later checked call leads into it). Unchecked, the scan put old return addresses left in the driver's locals into the chain: cgame's system call dispatcher inside a libnx wait, in most samples of an RTCW profile;
  - a sample at an SVC is a wait, and the report names the game function that waited and the system call it waited in;
  - each sample carries the frame phase and the A/B label, so one profile covers every state of a session.
- **Per-thread CPU in the periodic report** (Manhunt, `[perf]` every 2 s): game, graphics, audio and APU apart. Busy per core and every thread of the process: guide 11.
- **Wall and CPU time per part of the frame** (RTCW): the difference is waiting (guide 01).
