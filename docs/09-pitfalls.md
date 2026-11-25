# Pitfalls

Things that cost time. Each has a short fix.

| Symptom | Cause | Fix |
|---|---|---|
| `.sh` scripts do not run in the container | CRLF checkout on Windows | `core.autocrlf false`, `core.eol lf`, check out again |
| The build runs out of memory | Docker VM with ~7 GB and huge generated C files | 4 jobs (`CPUS=4`) |
| Docker disappears mid-work | The PC went to sleep | Restart Docker Desktop |
| Changing one file's `-O3` does not change the binary | Per-file `COMPILE_OPTIONS` do not rebuild the object (Makefile) | Delete the `.o` or use a new build folder |
| The build breaks after the post-recompile step | A new name equal to one the recompiler already uses (`_r`) | Own prefix (`_plr`, `_plmb`) |
| "Undeclared" errors after removing runtime definitions | Missing `extern` declaration in the `#else` | Patch with `#ifndef ... #else extern ... #endif` |
| The level marker prints garbage ("ls") | It searched for `levels\` in the whole string | Compare only the start (`strncasecmp(p, "levels\\", 7)`) |
| Underrun count far too high | The log repeats the running total | Count the new-events field, `(+N)` |
| Per-level saves of 49 GB | Partition images copied along | Leave out `Partition*.img` |
| The one-level test starts somewhere else | Several saves, and the game picks an old one | Keep only the newest save |
| `gcov-tool merge-stream` skips everything ("Skip") | The profile folder does not exist | Create it first |
| Profile with doubled counts | Merged twice into the same folder | Delete and merge once |
| No PGO stream on the card (LEGO) | Thread created at a priority that is not allowed (0x3F) | 0x3B, and log the creation result |
| Missing `.gcda` files on Windows (LEGO) | Names over 259 characters | Short profile folder, names rewritten before the merge |
| Emulator captures 3/4 black | Ryubing cuts every readback to 1/4 of the width | Read through a 4× wider target (`tools/gl_readback_wide.c`) |
| The emulator finds no controller | No player 1 configured | `--input-id-1 0` |
| Restarting the game from inside fails in Ryubing | `appletRestartProgram` returns rc 19289 | One run per process |
| Comparing two builds' FPS in the emulator | The script drifts: the same level had 335 to 573 draws per frame | Use the emulator only for "nothing broke"; speed on the console |
| Holding a button at boot to switch modes does not work (LEGO) | The tester launches from sphaira, not the home menu | A second NRO with the option on |
| Multi-line text breaks in a shell command | Wrongly escaped `\n` in a heredoc | Write the script to a file, or `NL = chr(10)` in Python |
| `git cherry-pick -q` fails | The option does not exist | Drop `-q` |
| A crash in the emulator, and fixes built on guesses do nothing (LEGO) | The location was in the Ryujinx log all along | Read `PrintGuestStackTrace` and the registers, `addr2line` on the ELF (guide 05) |
| Run-time memory mapping fails on the console with rc 0xCE01 after a few mappings (LEGO) | The kernel limits extra mappings; the emulator runs never reached that many | Map at boot, or one large range (guide 11) |
| A crash far from its cause after the memory map changed (LEGO) | Guard patches in the generated code with fixed address ranges | One header for the ranges, a script for the guards (guide 03) |
| A replay or a reused buffer reads old data (LEGO) | `NtFreeVirtualMemory` did nothing; the game expects decommitted pages to come back zeroed | Zero decommitted and released ranges (guide 11) |
| A thread holds the turn forever after another exits (LEGO) | A resume put an exited thread back in the scheduler | Mark gone threads and refuse them; a watchdog (guide 11) |
| A strong override is never called (LEGO) | Callers in the same generated file use a local alias | Hook a function whose callers are in other files (guide 07) |
| A fix looks twice as fast in the emulator and is slower on the console (LEGO) | Emulator timing differs, e.g. the movie fence wait | Speed claims from the console only (guide 07) |
| A and B swapped with SDL on the Switch (RTCW) | SDL's built-in Switch mapping is by position, not by the label on the button | `SDL_GAMECONTROLLERCONFIG` with a mapping by label, set before SDL starts (guide 12) |
| The system keyboard opens by itself and stays up (RTCW) | `SDL_StartTextInput` on the Switch shows the software keyboard | Do not call it; open the keyboard when a text field is clicked (guide 12) |
| Timed pad scripts stop working after a menu change (RTCW) | What the script clicked moved (menus made 16:9) | Steps that wait for the game (guide 05) |
| The emulator shows the same FPS on every map (RTCW) | Ryubing presents at the PC monitor's rate | Thread CPU time per frame on a fixed scene (guide 01) |
| High CPU time in the renderer, and no CPU change helps (RTCW) | `glFinish` and fence waits spin on the Switch's Mesa | Wall against CPU time, and the profiler (guides 01 and 07) |
| A new path without a GPU wait still waits (RTCW) | The old sync path also cleared a flag that made the swap call `glFinish` | Check what else the replaced code set (guide 07) |
| A performance configuration is accepted and nothing gets faster (RTCW) | The CPU boost for loading is a configuration of its own, with the GPU at 76.8 MHz, and wins while on | Read the real clocks (`clkrst`); boost only while loading (guide 07) |
| Loads get slower after limiting the CPU boost to the load functions (RTCW) | The rest of the load (UI restart, reads between) ran at 1020 MHz, the file service too | The boost from connecting to the first frame in game (guide 12) |
| Every start does a second video restart, from 640×480 (RTCW) | Closing from HOME never quits: a leftover PID file reads as a crash, and the engine picks "safe" video settings | Only report the PID file on the Switch (guide 12) |
| A script waits forever after loading a save (RTCW) | It waited for a pregame screen, which a save does not have | Wait for play, and load the save from another map (guide 05) |
| The GPU timer says less than the frame takes (RTCW) | Mesa's GPU clock runs at 0.614 of real time on the console | Calibrate against the frame period (guide 07) |
| Loads slow, the profile full of `unzOpenInternal` (RTCW) | Quake III opens the pk3 again (and searches its directory) for every file a game module opens | `unzReOpen`: copy the open pak's state (guide 12) |
| A save takes seconds (RTCW) | newlib's small stdio buffer: a write to the card every 1 KB | `setvbuf` 64 KB on written files (guide 12) |
| A profile names the wrong functions (RTCW) | Named with the ELF of another build | Keep each tested build's ELF beside its logs |
