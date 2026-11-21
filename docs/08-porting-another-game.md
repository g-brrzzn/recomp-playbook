# Porting another game

Written from LEGO (Xbox 360). None of this has been tried on another game yet. The effort for a new game is only known after its executable has been analysed.

## What carries over

- **The pipeline:** recompiler, build, PGO, release tools and the passes over the generated code.
- **The image from the disc:** building the game image from `default.xex` (decrypt, decompress, resolve imports), on a PC, for any game.
- **The kernel:** the kernel and XAM exports (threads, events, files, saves, memory, the GPU ring and its interrupts).
- **The GPU:** PM4 command recording, shader translation, GL replay on Mesa, and the caches.
- **The Switch side:** audio, controllers, saves, logs, the fourth core and the automated tests.

## What belongs to each game

An inventory (`port_inventory.py`) lists every game address the runtime uses, by region. LEGO had 349. SDK regions (D3D, XAudio, video, network, kernel) can be found by signature. Engine and game regions, by signature if the engine is close; otherwise by behaviour.

## Finding functions by signature

`find_functions.py` builds a masked signature of each function the runtime uses (branch targets and 16-bit immediates hidden, everything else exact) and searches for it in the other game's image. Each function comes out unique, ambiguous or missing.
- On LEGO itself: 212 of 246 functions found only where they are; 34 ambiguous, all tiny.
- With the same SDK version it should match almost word for word. With another version, or code the studio changed, it will be by behaviour.

## Steps

1. **Image and analysis.** Build the image. Find the switch tables and the register save/restore helpers.
2. **Recompile.** Write the new recompiler config and run the passes over the generated code, including the search for operations the recompiler leaves empty (guide 03).
3. **Map the addresses.** Signatures for SDK and engine; then region by region from the inventory. Each patch needs the other game's address, or a reason it is not needed there.
4. **Boot in the emulator first** (guide 05): many boots a day without a console. Milestones:
   - H0: reaches the entry point and the first frame;
   - H1: title and menus;
   - H2: bounded gameplay (not a finished port).
5. **Then the console:** memory, speed and driver.

## Known risks

- **Memory:** LEGO uses ~1.9 GB. A game with larger levels may not fit without work on the GL copy of guest memory.
- **Speed:** LEGO's heavy scenes run near 30 FPS in handheld. A heavier game will run slower.
- **Engine changes:** where the code changed, signatures miss, and each fix (loaders, jobs, streaming) has to be found again from the logs.

## For original Xbox games (Manhunt)

xboxrecomp already provides the runtime, the kernel and an NV2A renderer. Manhunt's own work was the post-recompile step (guide 03), the tests (guides 05 and 06) and PGO (guide 04). All of it applies to another Xbox game with the same recompiler.
