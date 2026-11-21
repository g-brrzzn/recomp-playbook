# GPU, video and cores

Almost all of this comes from LEGO, which uses OpenGL on Mesa/nouveau. Manhunt also uses Mesa/nouveau, but there the CPU was the limit (a 2.5× faster GPU changed nothing).

## Handheld GPU clock (LEGO)

A homebrew starts with the GPU at 307.2 MHz in handheld mode. The official configuration `0x92220008`, through `apmSetPerformanceConfiguration`, gives a 460.8 MHz GPU and 1331.2 MHz memory. It is not an overclock: it is a profile the system itself uses.
- In LEGO, handheld was GPU-limited, and this clock became the default.
- The call returns before the clock changes.
- The IDs mean nothing on their own: `0x92220007` is another combination (memory at 1600 MHz).
- It costs battery and heat. Say so to players.

## Fourth core (LEGO)

A homebrew normally gets 3 cores. Launched from a title whose NPDM allows core 3, the port puts background work there: audio and XMA.
- **Run 112, docked:** heavy frames ~12.5 % faster than run 102 at matched load (90 % interval: +2.8 to +23.1). The nvc0 translation reuse came in at the same time, so the gain is not the core's alone. The likely reason: XMA left core 2, which it shared with Mesa's worker.
- **What did not work:** moving the GPU walker to core 3. Frames ended later, because core 3 has system threads ahead of it and every IB moved the thread between cores 0 and 3.
- The emulator has no core 3, so this path can only be tested on the console.

## Shader caches (LEGO)

- **Mesa's disk cache** enabled and on the card: worker time in a session fell from 259 s to 41.6 s.
- **nvc0 translations on the card** (log116): Mesa's cache stores only the first part of the compile (GLSL). nouveau's back end (nv50_ir) ran again every session: ~80 % of a program's cost, ~95 ms on the Switch. Now each translation is appended to a file on the card, and the next session loads it before its first translation. Precautions:
  - pointers zeroed in each record, and each fixup's function stored as a number;
  - a checksum per record; a cut record is dropped;
  - the first 8 loaded translations are redone and compared. On any difference, everything is dropped and the file starts over;
  - the file depends on the Mesa version and codegen settings, not on the port's build;
  - a switch turns it off.
- **A cache-free session on the console, without deleting anything:** `MESA_GLSL_CACHE_DISABLE=true` plus the port's switches.

## ZCULL: exact, no gain (LEGO)

ZCULL was off in Mesa's nvc0 (under `#if 0`). It was turned on, with a pixel comparison (`[ZCULLCHECK]`). Result in run 62: **exact, no gain**. Every draw that writes depth in this game has a real alpha test, and ZCULL cannot learn depth from draws that may discard pixels. Before trying it, check how many depth draws do not discard.

## Video through FFmpeg instead of the recompiled decoder (LEGO)

The game's recompiled WMV3 decoder ran at ~1/3 of real time on the console: sound and picture drifted apart, and the end looked hung. The replacement:
- FFmpeg's WMV3 decoder, fed through the game's own data callbacks, with the Y/U/V planes written where the game expects them;
- on the console (run 123): 16 ms per frame, good picture;
- a switch goes back to the game's decoder.

Bugs that came along, and that apply to any player:
- VMX128 registers that nothing in the recompiled code initialises (the runtime now gives them the right values);
- tearing: the player rewrote a texture the renderer had not read yet. The movie's fence wait now also waits until the renderer is at most one frame behind (on the console: no tearing, the 61 s trailer in 73.5 s instead of 68 s);
- black screen at the end: the scheduler gave the turn to a thread that had already exited.

## One tile instead of three (LEGO)

The game drew its world three times per frame because of the 360's EDRAM. The engine's layout function had a plain path; forcing that path, without changing MSAA or resolution, was one of the two largest CPU steps of the port. In another 360 game, look for what EDRAM makes the engine repeat.
