# Porting an open-source engine

From RTCW: the single-player game of Return to Castle Wolfenstein on the Switch ("Return to Castle NX"), built from **iortcw** (id Tech 3), with libnx, SDL2 and devkitPro's Mesa. There is no recompiler: the engine is C source, and the game's data comes from the player's own copy. Most of guides 01, 05, 06 and 09 applies as it is; this guide is what differs.

## Keep the upstream tree almost untouched

- The port lives in its own folder (`nx/`); the engine's `Makefile` gets two `-include` lines that do nothing unless the platform is the Switch.
- Changes inside the engine are small and each marked with a comment (`Return to Castle NX`), listed in one table in the port's docs, most of them a few lines.
- Hooks without editing: `-Wl,--wrap=<function>` puts the port in front of an engine function called from another object file. RTCW wraps the input queue (the controller in menus), the parts of the frame (per-phase timing, guide 01), the load functions (the CPU boost, below), file reads and `threadCreate` (guide 11). Like the strong overrides of guide 07, a wrap does not see calls from inside the same object file, nor calls through a function pointer set in it (console commands).

## Game modules without `dlopen`

Quake III engines load the game logic, the client game and the menus as shared libraries, three times or more per session. A homebrew has no dynamic loader, so each module is linked into the executable:
- each module's objects are pre-linked with `ld -r` and a small linker script that puts its data and bss in sections of their own, with start and end symbols (section addresses at 0, or `ld -r` complains);
- `objcopy` renames the entry point (`dllEntry`, `vmMain`) to a per-module name, then keeps only those global, so the three modules' identical names do not clash. Two passes: the "keep global" list must use the new names;
- a table maps the module name to its entry points, and the engine's module loader asks it before looking on disk.

**Reloading.** A shared library comes back with fresh globals; a linked-in module would keep the last map's. The port snapshots each module's data section at its first load and, on every later load, copies the snapshot back and zeroes its bss. In RTCW, `levels` (all 26 campaign maps in a row, guide 05) loaded the game and client-game modules 26 times each with no error (emulator).

**State shared between the engine and a module lives in the engine.** With only the entry points global, the engine cannot see anything a module defines, but a module still links against the engine's symbols. A flag both need (in RTCW, "the menus are driven by the pad", set by the engine's input code and read by the menu module) is defined in the engine's code and declared `extern` in the module. Defined in the module, the engine's link failed.

## Controller first, on menus made for a mouse

- **Focus, not a cursor.** RTCW's menus react to a mouse cursor and clicks (the briefing before every map is one big button). A first version put a cursor on the sticks; steering it around every page was slow. Now the d-pad and the left stick send arrow keys (with repeat: 380 ms, then every 120 ms) that move a focus from item to item, A acts on the focused item, B goes back:
  - the cursor is moved to the centre of the focused item and hidden, so the menu code's own mouse-over logic (highlights, tooltips, the item a click goes to) works unchanged; the right stick moves it again, and any mouse event leaves the focus mode;
  - a menu opens with its first item focused, and a yes/no question with **No** focused, so two presses of A never quit by accident;
  - A on a list runs what a double click does (load the save), A on a slider does nothing (left and right change it); up and down leave a list at its ends instead of stopping there;
  - all of it in the menu code's item navigation (`Menu_SetNextCursorItem` and its kin), none in the menu files.
  In a cutscene, A, B and + skip it.
- **Controls in the pad's names.** The controls page searched only the keyboard's 256 keys and showed PC keys. It now searches the engine's pad key range too and names them as the Switch does (ZR, A, the sticks). While it waits for a new key, the pad's buttons pass through raw (not mapped to menu keys) and + cancels. A test that rebinds a control puts it back at the end (guide 05).
- **Take out what means nothing on the console.** Mouse settings, the PC's video mode, colour depth, fullscreen, graphics-card extensions and the quality presets (which set 640×480), multiplayer and mods: the port removes those items when a menu is parsed, chosen by the setting they change or by their text, and moves the rows below them up so no gap is left. One list in the code, no edits to the game's menu files (they stay the player's data).
- **Buttons by label.** SDL's built-in Switch mapping is by position, so A went back and B confirmed (console). An `SDL_GAMECONTROLLERCONFIG` mapping by label, set before SDL starts, fixed it.
- **The keyboard only when asked.** `SDL_StartTextInput` shows the Switch's software keyboard; SDL called it at every input restart and left it up (console). The port opens the keyboard when a text field is clicked instead.
- **Fewer steps for common things.** Saving needed typing a name: the save page now fills one in (map, date, time). A quick save and a quick load sit on X and Y in the pause menu, the load behind a confirmation. All of it in the menu code (GPL, part of the engine), none in the game's data files, which stay the player's.

## 16:9: look for the engine's own option first

The menus and HUD are laid out for 640×480 and were stretched to 16:9 (an oval crosshair). iortcw already had `cg_fixedAspect`: 2 keeps proportions and anchors the HUD to the corners. Turning it on, with emulator screenshots of the menu, the briefing, the HUD and the pause menu at 0, 1 and 2, was the whole fix. Check a modern fork's options before writing your own.

## Settings: the first run and the player's changes

- The engine applies its own hardware preset on the first run (in RTCW, `r_mode 3`: 640×480). The port puts the Switch's resolution back after it.
- The port's own defaults (vsync, frame cap, texture size, 16:9) are applied once and versioned: each new version sets only what it adds, so a player's earlier changes stay.
- `fs_basepath` and `fs_homepath` are forced to the port's folder on the card: the engine's guess pointed at the homebrew folder.
- **Closing from HOME never quits.** ioquake3-based engines keep a PID file while running and take a leftover one for a crash: the next start asked for "safe" video settings (640×480, windowed), which the port then undid with a second video restart, at every start. On the Switch, only report it.

## Loads and saves on the SD card

Every small read or write is a request to the system's file service, and Quake III's file code makes many. What the profile (guide 06) found, with the console's numbers:
- **A zip opened again for every file.** Quake III's file system gives each file the game modules open (`uniqueFILE`) its own `unzOpen` of the pk3, and `unzOpen` searches the zip's central directory from the end of the file: about 70 small reads each. It was most of the load samples, mostly the UI parsing its menus (the engine restarts the UI at every map load). Fix: an `unzReOpen` that copies the already open pak's state and opens only a new file stream (ioquake3 once had one).
- **Saves flushed every 1 KB.** newlib's default buffer is small, and RTCW's savegame code writes in small pieces: a save took 3.5-4.6 s, 80 % of it waiting in `fsFileWrite`. Fix: `setvbuf` with 64 KB for files opened for writing: 0.15-0.6 s.
- **The CPU boost over the whole load** (guide 07). Only in the server's and cgame's load functions, it left the UI's restart and the reads between at 1020 MHz, the file service included, and loads got slower than with the boost always on. Fix: on from the client connecting to its first frame in game, and around every video restart.
- Together, a map load went from 33 s to 14-15 s (from 24.5 s with the boost always on), and the start to the main menu from 15.4 s to 1.9 s (console).
- To find the unboosted part: split the load phases' profile samples into those inside the boosted functions and those outside.
- **Asking the card for files that are not there.** Before a file inside a pk3, Quake III looks for a loose copy in every search folder: a `stat` and a failed `fopen` each, and on the card each is a slow metadata request. It was ~3 s of a 13-16 s load (14 % of the load samples). Fix: in the port's `fopen`, remember which folders do not exist (a small hash of folder names) and fail a read in one at once; clear the memory whenever the game makes a folder. With larger inflate reads (128 KB) in the same build: loads 2-2.6 s shorter (escape1 16.1 → 13.5 s), the `fopen` 14 % → 1 % of the load samples (console).
- **What sped up the emulator did not speed up the console.** The pk3s read through a 64 KB buffer of the port's own in zlib's file layer (newlib's stdio has a 1 KB buffer and drops it on every seek): emulator loads 18-30 s → 6-8 s, console loads unchanged. The emulator's file costs are not the console's (guide 05): profile loads on the console, with the load marked as its own phase in the profiler (`--label`, guide 06), before choosing what to fix.
- **Keep the boost a little past the load.** The first frames in game still load (shaders, sounds). The port keeps the boost until 15 frames in a row take under 40 ms, at most 4 s after the first frame (console: it ended 0.35-1.85 s after it).

## HOME and sleep

A per-frame check of the applet's focus state never sees HOME or sleep: while the game is in the background its threads are stopped, so the frame that would look comes after the return. `appletHook` gets the applet's messages as they arrive (focus, suspend, resume, operation mode), so log and react to them there (**UNVERIFIED** on the console: the session after the change logged no applet message, and the tester may not have pressed HOME). On the console, the game came back from HOME and sleep fine (8 s and 1.2 s frames on the return).
