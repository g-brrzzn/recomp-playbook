# Porting an open-source engine

From RTCW: the single-player game of Return to Castle Wolfenstein on the Switch ("Return to Castle NX"), built from **iortcw** (id Tech 3), with libnx, SDL2 and devkitPro's Mesa. There is no recompiler: the engine is C source, and the game's data comes from the player's own copy. Most of guides 01, 05, 06 and 09 applies as it is; this guide is what differs.

## Keep the upstream tree almost untouched

- The port lives in its own folder (`nx/`); the engine's `Makefile` gets two `-include` lines that do nothing unless the platform is the Switch.
- Changes inside the engine are small and each marked with a comment (`Return to Castle NX`), listed in one table in the port's docs. RTCW touches 18 engine files, most of them in a few lines.
- Hooks without editing: `-Wl,--wrap=<function>` puts the port in front of an engine function called from another object file. RTCW wraps the input queue (the controller in menus), the server and client frames, the sound update, the swap, the command buffer and file reads (per-phase timing, guide 01), and `threadCreate` (guide 11). Like the strong overrides of guide 07, a wrap does not see calls from inside the same object file.

## Game modules without `dlopen`

Quake III engines load the game logic, the client game and the menus as shared libraries, three times or more per session. A homebrew has no dynamic loader, so each module is linked into the executable:
- each module's objects are pre-linked with `ld -r` and a small linker script that puts its data and bss in sections of their own, with start and end symbols (section addresses at 0, or `ld -r` complains);
- `objcopy` renames the entry point (`dllEntry`, `vmMain`) to a per-module name, then keeps only those global, so the three modules' identical names do not clash. Two passes: the "keep global" list must use the new names;
- a table maps the module name to its entry points, and the engine's module loader asks it before looking on disk.

**Reloading.** A shared library comes back with fresh globals; a linked-in module would keep the last map's. The port snapshots each module's data section at its first load and, on every later load, copies the snapshot back and zeroes its bss. In RTCW, `levels` (all 26 campaign maps in a row, guide 05) loaded the game and client-game modules 26 times each with no error (emulator).

## Controller first, on menus made for a mouse

- **A cursor on the sticks.** RTCW's menus react to a mouse cursor and clicks (the briefing before every map is one big button). While a menu has the input, either stick moves the cursor, A clicks, B goes back, and the d-pad sends arrows. In a cutscene, A, B and + skip it.
- **Buttons by label.** SDL's built-in Switch mapping is by position, so A went back and B confirmed (console). An `SDL_GAMECONTROLLERCONFIG` mapping by label, set before SDL starts, fixed it.
- **The keyboard only when asked.** `SDL_StartTextInput` shows the Switch's software keyboard; SDL called it at every input restart and left it up (console). The port opens the keyboard when a text field is clicked instead.
- **Fewer steps for common things.** Saving needed typing a name: the save page now fills one in (map, date, time). A quick save and a quick load sit on X and Y in the pause menu, the load behind a confirmation. All of it in the menu code (GPL, part of the engine), none in the game's data files, which stay the player's.

## 16:9: look for the engine's own option first

The menus and HUD are laid out for 640×480 and were stretched to 16:9 (an oval crosshair). iortcw already had `cg_fixedAspect`: 2 keeps proportions and anchors the HUD to the corners. Turning it on, with emulator screenshots of the menu, the briefing, the HUD and the pause menu at 0, 1 and 2, was the whole fix. Check a modern fork's options before writing your own.

## Settings: the first run and the player's changes

- The engine applies its own hardware preset on the first run (in RTCW, `r_mode 3`: 640×480). The port puts the Switch's resolution back after it.
- The port's own defaults (vsync, frame cap, texture size, 16:9) are applied once and versioned: each new version sets only what it adds, so a player's earlier changes stay.
- `fs_basepath` and `fs_homepath` are forced to the port's folder on the card: the engine's guess pointed at the homebrew folder.

## Loads (open)

A map took 21-33 s to load on the console (9-11 s in the emulator), of which 6-8 s were spent reading 73-92 MB from the card, the rest in the engine building the level. Not worked on yet.
