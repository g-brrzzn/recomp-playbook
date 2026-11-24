# Method: measuring without fooling yourself

This held in every port, and it saved the most time.

## 1. Know what each place proves

| Where | Proves | Does not prove |
|---|---|---|
| Compiling | That it compiles and links | That it runs |
| PC (tool tests) | That the tool does what it says | Anything about the game |
| Emulator (Ryubing) | No hang, no new error, the same images, the same game played; the CPU work of a change, as the thread's CPU time on a fixed scene (RTCW, below) | **Frame rate, GPU time, how frames reach the screen** |
| Console | Speed, memory, driver | — |

In Manhunt, the same level in the emulator had 335 to 573 draws per frame depending on the run, and the same audio binary varied from 419 to 448 ms/s of work. With that much noise, the emulator cannot rank builds by speed.

In LEGO, the emulator runs the game at about 35 FPS on the PC, which has nothing to do with frame time on the Switch.

In RTCW the emulator did rank CPU-side changes, measured another way:
- **What:** the main thread's CPU time per frame from the kernel (`svcGetInfo` `InfoType_ThreadTickCount`), with the player standing still at the start of a map (the same scene every run), no frame cap. Not FPS: Ryubing showed 165 FPS on every map, the PC monitor's rate.
- **Against the console:** in the same scenes the console took about 1.5 to 2.5 times the emulator's CPU time.
- **Noise:** about 6 % between runs with 15 s per scene, about 10 % with 8 s.
- **What it found:** the profiler (guide 06) showed a wait for the GPU in every frame, in the emulator first; removing it cut the client's time in that scene by 68 % there. On the console the gain did not show yet: another wait took its place (section 9).
- **What it cannot do:** GPU time (Ryubing's timer queries return 0) and when frames reach the screen. Those stay console only.

**Rule:** every number carries the place where it was measured. Anything not measured on the console is written as **UNVERIFIED**.

## 2. Every change behind a switch

- Manhunt: `MANHUNT_MEMBASE_LOCAL=0`, `MANHUNT_GUEST_REGS=0`, `MANHUNT_APU_O3`, and `MANHUNT_PGO` (off when unset).
- LEGO: "A/B letters" (`LSWTCS_ABSTATES=MAPX...`): each change is a letter that can be switched on or off within one session.

When something breaks on the console, the tester turns a switch off instead of waiting for a new build. And an A/B does not need two builds.

## 3. Null control: measure your own noise

In LEGO, the A/B state list holds two identical states (the same letters, plus a `0` that switches nothing). The difference between them is the method's noise.
- Measured in run 91: two identical states in a 3.5-minute session differed by −4.3 % (90 % interval: −12.2 to +4.7).
- So an effect under ~10 % needs longer or repeated sessions.

In the LEGO emulator (A/A, the same build three times): in the heavy level every counter stayed within 2.6 %; in the hub, within 4.8 % (vertices 11 %). That is why changes are judged in the heavy level.

## 4. Compare only scenes of similar load

FPS depends on the scene. Both ports split samples by load:
- Manhunt: samples above 20,000 vertices per frame (`tools/ab_compare.py`).
- LEGO: frames binned by draw count (700–1,299, 1,300+) and compared bin by bin ("load-matched").

A metric that varies less than FPS: **CPU cost per call of a game function** (LEGO, `guest_call_cost.py`): 151–158 ns across sessions, about 3 % spread. PGO brought it to 140 ns.

## 5. Alternate the builds

For two builds on the console: a, b, a, b, in the same mode (handheld or docked), on the same charger, at the same clocks. A single run of each is not enough for a difference under ~5 %.

## 6. Count before optimizing

- Before trying to merge draws, count how many could be merged. (One such count came out at zero in Manhunt.)
- LEGO's rule for rewriting a function by hand: it must hold at least 2 % of the thread that limits the frame, and the removable cost must show in the samples. None passes today.
- Profile before guessing: in LEGO, the first profile (run 8) showed the largest wait was the port's own file polling, not the game.

## 7. Short, honest reports

Give the gain of each console session against the last one on the same scenes, in %, including when it is zero. In RTCW, from the second to the third session the first level's average FPS rose 11 % and its 95th and 99th percentile frame times fell 15 % and 18 %, while the scenes measured standing still stayed at exactly 30 FPS in all three: the stutter got better, the frame rate did not, and the report says so.

Each run gets an entry with the build, what changed, what is expected, what was measured, where, and what is still open. LEGO has one entry per build (log1 to log135) and one per console session (run 1 to 135). A result that does not repeat is written down as such.

## 8. A console test request says

- what changes from the previous build;
- the expected result;
- how long it takes and which logs to bring back;
- which decision the result will allow.

Do not repeat the same test just to "see if it hangs again".

## 9. Waiting can look like work

Log, for each part of the frame, both the time it took and the thread's CPU time in it (RTCW: cgame, the renderer's front end, its back end, the swap). The difference is waiting. Two cases from RTCW, on the console:
- A frame part that took 30 ms with 2.8 ms of CPU was asleep, waiting for the swap chain: no CPU work would speed it up.
- A part with 26 ms of CPU time in 30 ms was not working either: `glFinish` on the Switch's Mesa waits by spinning, so a wait for the GPU counted as CPU time (guide 07). Only the profiler's samples (where the time went: `nouveau_fence_wait`) told the two apart.

And one fix can hide another: the old path waited for the GPU by sleeping, so when it was removed, the next wait down the frame (the spinning one) took its place and the frame rate did not move.
