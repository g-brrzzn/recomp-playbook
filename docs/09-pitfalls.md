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
