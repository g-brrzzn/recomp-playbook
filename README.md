# recomp-playbook

A brief condensation of the techniques, tools and optimizations I used in my Nintendo Switch ports that worked. It is a collection of debugging techniques, optimizations and a few studies that may turn out to be useful.

The ports it comes from:

- **Manhunt** (Xbox → Switch, with xboxrecomp).
- **LEGO Star Wars: The Complete Saga** (Xbox 360 → Switch, with XenonRecomp).
- **Return to Castle Wolfenstein**, single player ("RTCW": the open-source iortcw engine on the Switch, no recompiler).

Each item says which port it came from, what was measured and where (console or emulator). Anything not verified is marked as such. Studies that brought no gain are here too, so nobody has to repeat them.

## Guides

| Guide | Topic |
|---|---|
| [docs/01-method.md](docs/01-method.md) | Measuring without fooling yourself: console against emulator (and the CPU time the emulator can rank), A/B, null control, switches to turn things off, waiting that looks like work |
| [docs/02-reproducible-build.md](docs/02-reproducible-build.md) | Docker pinned by digest, clean builds, memory, line endings |
| [docs/03-generated-code.md](docs/03-generated-code.md) | Changes to the generated C: memory base, registers, `-Os`, `-O3`, addressing, what gave no gain |
| [docs/04-pgo-on-switch.md](docs/04-pgo-on-switch.md) | PGO in a homebrew: counters streamed to the SD card, merging on the PC, pitfalls |
| [docs/05-emulator-testing.md](docs/05-emulator-testing.md) | Headless Ryubing, scripted pad and scripts that wait for the game, per-level tests, per-level saves, shorter runs, same-game check, locating a crash from the Ryujinx log |
| [docs/06-console-testing.md](docs/06-console-testing.md) | A/B kit, per-build logs, one session answering many questions, comparing only scenes of similar load, measured noise, profilers |
| [docs/07-gpu-video-and-cores.md](docs/07-gpu-video-and-cores.md) | Handheld clock, fourth core, shader and translation caches, ZCULL, video through FFmpeg, movie tearing, resolve hand-over, GL calls that wait on the Switch's Mesa, GPU time per part of the frame, render resolution |
| [docs/08-porting-another-game.md](docs/08-porting-another-game.md) | What carries over to another game, finding functions by signature, milestones |
| [docs/09-pitfalls.md](docs/09-pitfalls.md) | Things that cost time |
| [docs/10-licences.md](docs/10-licences.md) | What never goes in here, licences |
| [docs/11-runtime-memory-and-threads.md](docs/11-runtime-memory-and-threads.md) | Guest memory map, reservations against commits, the console's mapping limit, the cooperative scheduler, busy cores and threads |
| [docs/12-open-source-engine-ports.md](docs/12-open-source-engine-ports.md) | Porting an open-source engine: upstream kept untouched, game modules without `dlopen`, a controller on mouse menus, 16:9, settings |

## Tools

Generic versions, with no game name inside. Each one explains its usage at the top of the file.

| Tool | What it does | From |
|---|---|---|
| [tools/post_lift.py](tools/post_lift.py) | Reversible edits of the generated code, with marks and a byte-exact `--undo` | Manhunt |
| [tools/ryubing_run.py](tools/ryubing_run.py) | Runs an NRO in headless Ryubing, stops at the exit marker, summarises FPS, errors and levels, compares with a baseline, keeps a save per level | Manhunt |
| [tools/ab_compare.py](tools/ab_compare.py) | Compares two logs on heavy-scene samples only; `--by` compares scene by scene or A/B state by state | Manhunt; `--by` RTCW |
| [tools/pgo_stream.c](tools/pgo_stream.c) | Streams PGO counters to the SD card while the game runs | Manhunt and LEGO |
| [tools/pgo_merge.py](tools/pgo_merge.py) | Turns those streams into `.gcda` files and fixes each object's summary | Manhunt and LEGO |
| [tools/gl_readback_wide.c](tools/gl_readback_wide.c) | Reads a whole frame in Ryubing, which cuts every readback to 1/4 of the width | Manhunt |
| [tools/replay_check.py](tools/replay_check.py) | "Same game?" check of a scripted run (frames between state changes) and work per level against a baseline, with boot retries | LEGO |
| [tools/stage_console.py](tools/stage_console.py) | Stages a console test: label check, kept ELF, SD tree, hash manifest, test request | LEGO |
| [tools/widen_ptr_checks.py](tools/widen_ptr_checks.py) | Rewrites hard-coded guest pointer range checks into one helper, idempotent | LEGO |
| [tools/sched_watchdog.cpp](tools/sched_watchdog.cpp) | Cooperative scheduler: refuses exited threads, and a watchdog that reports and breaks a stalled turn | LEGO |
| [tools/sampling_profiler.c](tools/sampling_profiler.c) | Sampling profiler on the console: frame pointer chain through Mesa and libnx, waits told apart, samples tagged by frame phase and A/B state | RTCW, after LEGO's |
| [tools/profile_report.py](tools/profile_report.py) | Names those samples from the ELF: by phase and state, CPU work, inclusive, what waited and where; also names threads' creators | RTCW |
| [tools/core_usage.c](tools/core_usage.c) | Busy per CPU core, and every thread of the process with its creator and CPU share | RTCW |

The example configs in `examples/` are Manhunt's, except `replay_check.json` (LEGO's log lines). Tests are in `tests/`:

```
python -I tests/test_post_lift.py
python -I tests/test_pgo_merge.py
python -I tests/test_replay_and_staging.py
python -I tests/test_profiling.py
```

## Licence

MIT, see [LICENSE](LICENSE). Third-party licences of the ports are listed in [docs/10-licences.md](docs/10-licences.md).
