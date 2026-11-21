# recomp-playbook

A brief condensation of the techniques, tools and optimizations I used in my Nintendo Switch ports that worked. It is a collection of debugging techniques, optimizations and a few studies that may turn out to be useful.

The ports it comes from:

- **Manhunt** (Xbox → Switch, with xboxrecomp).
- **LEGO Star Wars: The Complete Saga** (Xbox 360 → Switch, with XenonRecomp).

Each item says which port it came from, what was measured and where (console or emulator). Anything not verified is marked as such. Studies that brought no gain are here too, so nobody has to repeat them.

## Guides

| Guide | Topic |
|---|---|
| [docs/01-method.md](docs/01-method.md) | Measuring without fooling yourself: console against emulator, A/B, null control, switches to turn things off |
| [docs/02-reproducible-build.md](docs/02-reproducible-build.md) | Docker pinned by digest, clean builds, memory, line endings |
| [docs/03-generated-code.md](docs/03-generated-code.md) | Changes to the generated C: memory base, registers, `-Os`, `-O3`, addressing, what gave no gain |
| [docs/04-pgo-on-switch.md](docs/04-pgo-on-switch.md) | PGO in a homebrew: counters streamed to the SD card, merging on the PC, pitfalls |
| [docs/05-emulator-testing.md](docs/05-emulator-testing.md) | Headless Ryubing, scripted pad, per-level tests, per-level saves, same-game check, locating a crash from the Ryujinx log |
| [docs/06-console-testing.md](docs/06-console-testing.md) | A/B kit, per-build logs, comparing only scenes of similar load, measured noise |
| [docs/07-gpu-video-and-cores.md](docs/07-gpu-video-and-cores.md) | Handheld clock, fourth core, shader and translation caches, ZCULL, video through FFmpeg, movie tearing, resolve hand-over |
| [docs/08-porting-another-game.md](docs/08-porting-another-game.md) | What carries over to another game, finding functions by signature, milestones |
| [docs/09-pitfalls.md](docs/09-pitfalls.md) | Things that cost time |
| [docs/10-licences.md](docs/10-licences.md) | What never goes in here, licences |
| [docs/11-runtime-memory-and-threads.md](docs/11-runtime-memory-and-threads.md) | Guest memory map, reservations against commits, the console's mapping limit, the cooperative scheduler |

## Tools

Generic versions, with no game name inside. Each one explains its usage at the top of the file.

| Tool | What it does | From |
|---|---|---|
| [tools/post_lift.py](tools/post_lift.py) | Reversible edits of the generated code, with marks and a byte-exact `--undo` | Manhunt |
| [tools/ryubing_run.py](tools/ryubing_run.py) | Runs an NRO in headless Ryubing, stops at the exit marker, summarises FPS, errors and levels, compares with a baseline, keeps a save per level | Manhunt |
| [tools/ab_compare.py](tools/ab_compare.py) | Compares two console logs on heavy-scene samples only | Manhunt |
| [tools/pgo_stream.c](tools/pgo_stream.c) | Streams PGO counters to the SD card while the game runs | Manhunt and LEGO |
| [tools/pgo_merge.py](tools/pgo_merge.py) | Turns those streams into `.gcda` files and fixes each object's summary | Manhunt and LEGO |
| [tools/gl_readback_wide.c](tools/gl_readback_wide.c) | Reads a whole frame in Ryubing, which cuts every readback to 1/4 of the width | Manhunt |

The example configs in `examples/` are Manhunt's. Tests are in `tests/`:

```
python -I tests/test_post_lift.py
python -I tests/test_pgo_merge.py
```

## Licence

MIT, see [LICENSE](LICENSE). Third-party licences of the ports are listed in [docs/10-licences.md](docs/10-licences.md).
