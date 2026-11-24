# GPU, video and cores

Almost all of this comes from LEGO, which uses OpenGL on Mesa/nouveau. Manhunt also uses Mesa/nouveau, but there the CPU was the limit (a 2.5× faster GPU changed nothing). RTCW (iortcw's GL1 renderer on devkitPro's Mesa 20.1) added what its OpenGL calls cost on that Mesa, at the end.

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

- **Mesa's disk cache** enabled and on the card. (An earlier version of this page credited it with worker time falling from 259 s to 41.6 s; those numbers are the nvc0 translations' below, measured with Mesa's cache already on.)
- **nvc0 translations on the card** (log116): Mesa's cache stores only the first part of the compile (GLSL). nouveau's back end (nv50_ir) ran again every session: ~80 % of a program's cost, ~95 ms on the Switch. Now each translation is appended to a file on the card, and the next session loads it before its first translation. Precautions:
  - pointers zeroed in each record, and each fixup's function stored as a number;
  - a checksum per record; a cut record is dropped;
  - the first 8 loaded translations are redone and compared. On any difference, everything is dropped and the file starts over;
  - the file depends on the Mesa version and codegen settings, not on the port's build;
  - a switch turns it off.
  - **Measured on the console (run 119, two sessions in a row; run 118 as the reference):** the second session loaded 1,348 translations (5 MB in 981 ms), checked 57 against a fresh compile with 0 differences, and built each program in 28 ms of worker time instead of 170-240 ms (compile worker time 259 s → 41.6 s). The whole saved list (~1,450 programs) was ready 36 s after boot; frames held for programs fell from 855 ms to 99 ms, the longest frame from 1,874 ms to 597 ms. The writing session paid for it (352 s of worker time against 259 s), because the first version flushed after every record; writing through a 256 KB buffer fixed that (a record cut by closing from HOME is dropped and redone next session).
- **Shader translations (guest shader → GLSL) on the card, keyed to the translator** (log122): the first version took the NRO's build ID as the file's identity, so every rebuild of anything started it over and the next session translated every shader again (a 2.1 s frame in run 120). Now the build hashes the files that decide a translation (the translator's sources, the GPU emulation headers, the SPIR-V Cross and glslang headers, the patch and the compile options) into a generated header, and the file survives builds that do not touch them. The first 8 saved translations per session are still redone and compared. Emulator: a rebuild that changed only the kernel loaded 152 of 153 translations, 8 checked the same. On the console (run 121) it started over once, as expected, when the identity changed format. Pitfall: a host test that compiles the cache code needs the build's generated folder on its include path.
- **A cache-free session on the console, without deleting anything:** `MESA_GLSL_CACHE_DISABLE=true` plus the port's switches.

## ZCULL: exact, no gain (LEGO)

ZCULL was off in Mesa's nvc0 (under `#if 0`). It was turned on, with a pixel comparison (`[ZCULLCHECK]`). Result in run 62: **exact, no gain**. Every draw that writes depth in this game has a real alpha test, and ZCULL cannot learn depth from draws that may discard pixels. Before trying it, check how many depth draws do not discard.

## Video through FFmpeg instead of the recompiled decoder (LEGO)

The game's recompiled WMV3 decoder ran at ~1/3 of real time on the console: sound and picture drifted apart, and the end looked hung. The replacement:
- FFmpeg's WMV3 decoder, fed through the game's own data callbacks, with the Y/U/V planes written where the game expects them;
- on the console (runs 123-126): 13-16 ms per frame, good picture;
- a switch goes back to the game's decoder.

**How it hooks in.** Only the codec is replaced; the game's player keeps its threads, audio, timing and textures. Four functions of the decoder are overridden (strong `PPC_FUNC` definitions, reached because their callers live in other generated files; see the pitfall below):
- *stream header*: a new stream starts here. Take the handle from the argument, not from the codec object, which still held the previous stream's handle on the second play. The header bytes are the data-callback calls made inside this function (LEGO: a 5-byte WMV3 sequence header).
- *data callback*: passed through, and appended to the header while a header read is active. Its arguments give pointer, size and a "more" flag; a distinct return code marks the last piece.
- *decode*: pulls one frame through the callback, decodes it with FFmpeg and marks one picture ready. The codec comes from the header (`00 00 01 0F` → VC-1, otherwise WMV3); width and height from the game's handle.
- *picture out*: copies the planes (I420 or YV12) only if a picture is ready, otherwise returns the game's "no picture" code. Writing a picture when none was waiting corrupted the game's queue.

Build and wiring:
- FFmpeg's own `configure` with `--disable-everything --enable-decoder=wmv3,vc1` makes the config; the aarch64 NEON files are listed by hand. `thread_count = 1`: the decode runs on the game's video thread.
- The bridge is a small C file in a static library. The runtime's weak references alone did not pull it into the link; a strong reference from the platform code did.
- Per-stream state lives in a shared pointer: the first version freed it while the old player's threads could still reach it.
- Every guest pointer the hooks touch goes through the runtime's address folding: a buffer can lie in another view of physical memory.
- The game's own decoder still allocates and frees its buffers around the hooks; logging reservations with both decoders gave the same sequence (guide 11), so the hook leaks nothing.

Bugs that came along, and that apply to any player:
- VMX128 registers that nothing in the recompiled code initialises (the runtime now gives them the right values);
- tearing (next section);
- black screen at the end: the scheduler gave the turn to a thread that had already exited (guide 11).

**Pitfall: overrides and same-file callers.** A strong definition replaces the generated weak one only for calls from other files: callers in the same generated file call a local alias and bypass it. Check where the callers live before choosing the function to hook.

## Tearing in movies with an asynchronous GPU replay (LEGO)

The player rotates three Y/U/V texture sets and rewrites one after D3D's fence says the GPU is done with it. In LEGO the fence completes when the PM4 walker has read the commands, but the render thread replays them later, sometimes frames behind, so it sampled a set the player had already rewritten.
- **Fix:** while a movie plays, a fence wait also waits (off the guest turn, at most 50 ms) until the render thread has read the textures of the published frames: a count of frames published at the swap against a count of frames whose textures the renderer has read.
- **How strict, measured on the console:**

| Variant | Tearing | 61 s trailer took | Time in fence waits | Waits at the 50 ms cap |
|---|---|---|---|---|
| No wait (run 123) | yes | 68 s | 0 | 0 |
| Copy the textures at each interrupt (run 124) | not judged | ~300 s (~6 fps) | | |
| Wait for every published frame (run 125) | gone | 102 s (~18 fps) | 3.1 s every 5 s | ~35 every 5 s |
| Allow 1 frame of lag (run 126, the default) | gone | 73.5 s | 1.3 s every 5 s | 19 in the whole movie |

- Waiting for every frame stalls: the render thread waits for the game's next swap while the game waits in the fence, until the cap. With three rotating sets, one frame of lag still keeps the renderer off the set being rewritten.
- **The emulator pointed the wrong way:** there the strict wait almost doubled the frames shown. Only the console showed its cost.
- Keep counters in the log (`[MOVIEFENCE]`: waits, the renderer's lag, time waited, cap hits) and the lag as a setting.

## Resolve hand-over instead of a copy (LEGO)

The 360 renders into EDRAM and "resolves" (copies) the result into a texture. In LEGO's renderer each resolve was a GPU copy: 4.7 ms of 29.3 ms of GPU time in heavy handheld frames (run 120).
- **Change:** when a colour resolve copies a whole render target, from its origin into the origin of a destination as wide as the target, and the target is cleared right after, the target's storage is handed to the destination instead of copied; the target takes the destination's old storage, so the two alternate.
- The render targets were 2,048 rows tall, so the destination samples through a view that sees only its rows: a Mesa edit adds a sampling height per texture object, used as the texture header's height. No shader changes.
- **Measured on the console (run 121, A/B every 6 s in one session, 75 heavy frames per state):** GPU per heavy frame, median, 26.70 → 25.38 ms (−5 %); resolves 4.79 → 3.15 ms; FPS at 1,300+ draws 32.8 → 34.1. The tester saw nothing wrong; on by default since.
- Judge the picture on the console: the emulator returned noise for resolved textures and looked dark with the change on.

## One tile instead of three (LEGO)

The game drew its world three times per frame because of the 360's EDRAM. The engine's layout function had a plain path; forcing that path, without changing MSAA or resolution, was one of the two largest CPU steps of the port. In another 360 game, look for what EDRAM makes the engine repeat.

## GL calls that wait for the GPU on the Switch's Mesa (RTCW)

Found with the sampling profiler (guide 06), which names the waits; Mesa 20.1 from devkitPro (nouveau, nvc0).

| Call | What it does here | Seen |
|---|---|---|
| `glFinish`, `glClientWaitSync` with a timeout | Waits by **spinning** in `nouveau_fence_wait`: the wait counts as CPU time (guide 01) | Console: 26 ms of CPU per frame in the back end |
| `glReadPixels` of one depth value (Quake III's flare test, every flare, every frame) | Waits for the GPU to finish everything sent so far: CPU and GPU take turns | Emulator, profiler: 22-30 % of the back end |
| The same read into a pixel buffer object | Still waits: Mesa reads depth as float through the CPU (`st_MapRenderbuffer`) | Emulator, profiler |
| An occlusion query's result (`GL_QUERY_RESULT`), even two frames later | Waits for the newest query, not that one: nvc0 keeps queries in one buffer | Emulator, profiler |
| `GL_QUERY_RESULT_AVAILABLE` | Never says yes without a wait elsewhere | Emulator |
| An occlusion query written by the GPU into a buffer of its own (`GL_ARB_query_buffer_object`), one buffer per frame of a ring of 3, read two frames later | **No wait**: the buffer's last GPU write was two frames ago | Emulator: back-end waits 30 % → 7.5 %, every result used, in-game screenshots the same as the engine's test |

RTCW's flare test now draws one invisible point where the flare is, 24 units nearer the eye (the engine's own tolerance), inside an occlusion query, and reads the result through the query buffer two frames later (33 ms: the flare fades anyway). Behind a switch, with the engine's read as the other choice.

**Pitfall that came with it:** the engine's flare test also cleared a "finished" flag (`glState.finishCalled = qfalse`), which made the swap call `glFinish`. The new path skipped the read but still cleared the flag, so every frame with a flare ended in a spinning `glFinish`. When replacing a sync path, check what else it set.

## GPU time by part of the frame (RTCW)

- A `GL_TIME_ELAPSED` query around each whole frame, read a few frames later, gives the GPU time per frame. Only one such query can be open, so parts of the frame use `glQueryCounter(GL_TIMESTAMP)` pairs instead: RTCW times each 3D scene that way, and the rest of the frame is 2D (HUD, menus).
- Works on the console. In Ryubing both return 0.
- With the GPU logged once a second, a session can switch one renderer feature off at a time and read its GPU cost (guide 06).

## Render resolution and the screen (RTCW)

- **Lower resolution:** rendering at 960×540 instead of 1280×720 (the system scales it up) halved the GPU time in handheld (forest 17 → 8.8 ms, the first level 13-14 → 7 ms) and the first level reached 60 FPS (console). A setting, applied at the next video restart.
- **The frame chain:** devkitPro's Mesa (`switch-mesa`, EGL platform patch) gives the window 3 buffers. `eglSwapInterval(0)` reaches the system but did not lift the 30 FPS on the console.
- **A frame queued before the GPU is done (open):** in a scene where the CPU took 5 ms and the GPU 8.8 ms, frames still came every 33 ms, the main thread asleep in `nwindowDequeueBuffer` 87 % of the back end. The same level at 960×540 with a `glFinish` before the swap ran at 60. The guess: a frame queued while the GPU still draws it misses a refresh. RTCW's fourth session compares no wait, `glFinish` and a fence polled with short sleeps. **UNVERIFIED**.
