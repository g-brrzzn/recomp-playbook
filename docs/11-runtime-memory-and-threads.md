# Runtime: guest memory and threads

From LEGO (XenonRecomp). The runtime there gives the game a 4 GB guest window in which a guest address is the memory itself: one 512 MB block is mapped at guest 0x80000000, and the 360's other views of physical memory (0xA0000000, 0xC0000000, ...) fold onto it (`address & 0x9FFFFFFF` for addresses with the top bit set). Most of what follows comes from that model, and applies to any runtime built the same way.

## Write the memory map down, in the code (LEGO)

Four bugs in a row came from not knowing who owned an address range. LEGO's map, as it ended up:

| Guest range | Owner |
|---|---|
| 0x82000000 + image size | the executable image |
| just below 0x83600000 | the main thread's stack (`r1 = 0x835FFFF0` at start, growing down) |
| 0x84000000-0x88000000 | the virtual heap (`NtAllocateVirtualMemory`), a bump allocator |
| from 0x88000000 | the physical allocator (`MmAllocatePhysicalMemoryEx`): first the main thread's PCR, then a 370 MB block the game asks for at boot (a constant in the image) |
| 0xA0000000-0xA2000000 | more physical blocks (the same memory as 0x80000000-0x82000000) |

What went wrong, each found from a crash:
- **The virtual heap ran into the physical blocks.** The bump allocator had 64 MB before 0x88000000 and never reused a range. Each new instance of the title movie's player reserved fresh heaps, so the second one put its picture buffer over the main thread's PCR, and a later read of `[[r13 + 256] + 332]` (the current thread) faulted at 0x11111xxx: the PCR page was full of 0x11 bytes (most likely picture data: near-black luma). Found with a probe in the getter's override that printed the PCR words (see guide 05 for how the fault was located).
- **The physical allocator's ceiling overlapped the virtual heap.** It handed out up to 0xA8000000, and 0xA4000000-0xA8000000 is the same memory as 0x84000000-0x88000000. Latent until the heap grew.
- **A range taken as free held the main stack.** Space after the image looked unused; zeroing a 6.6 MB block there wiped the stack, and the next player failed at once (console run 127).
- **Released pages kept their old bytes.** `NtFreeVirtualMemory` was a no-op. The player decommits its heap pages when a movie ends and commits them again for the next play, expecting zeros; it found old list nodes and pictures, and crashed in its file-block list. Zeroing decommitted and released ranges fixed the replay through the same player (emulator, then console run 125).

What to do:
- Keep the table above as a comment next to the allocators, and update it when anything moves.
- At every boundary, **refuse instead of overwriting**: a reservation that does not fit returns `STATUS_NO_MEMORY`. In LEGO that turned a crash into a failure the game survives (console run 128: the movie's second player failed, the screen stayed black, a button press went on to the game).
- Zero decommitted and released pages, as the console does.
- Watch aliases: every view of physical memory folds onto the same bytes, so a range is free only if it is free in every view.

## A reservation costs real memory here, not on the console (LEGO)

On the 360, `MEM_RESERVE` is address space; memory is spent only by `MEM_COMMIT`. In a runtime where address equals memory, every reserved byte is real. LEGO's growable heap reserves segments (2, 4, 8, then 16 or 32 MB when a new movie player starts), decommits their pages when they are free, and never releases the segments. That is free on the console and was the leak here (about 30 MB per new player).
- Before blaming your own hooks, log every reservation and release with the caller's `lr` and compare with the game's original path switched back on. In LEGO the sequence was the same with FFmpeg and with the game's decoder, so the leak was the game's, not the hook's.
- Lazy reservations (address space now, memory on commit) need a range outside the 512 MB and memory mapped on commit. Tried in LEGO (log135-136, behind switches, off by default): it hit the console's mapping limit (next section) and, mapped up front, froze the emulator when a second player started. **Not solved.**
- Reusing released ranges looked risky: with reuse, 2 of 10 new-player runs corrupted the game's heap; without it, 0 of 10. The samples were mixed with the stack bug above, so this is a caution, **not a proven cause**. The safe default kept the plain bump allocator.

## The console limits run-time memory mappings (LEGO)

Mapping heap memory into the guest window (`svcCreateCodeMemory` + `svcControlCodeMemory(CodeMapOperation_MapOwner)`) works at boot for every range. At run time, on the console, the fifth extra 1 MB mapping failed with **rc 0xCE01** (kernel module, description 103, out of a resource) after four had worked (console run 127). The emulator runs never needed more than four such chunks, so whether Ryubing has the same limit is not known; it did map one 64 MB range at run time.
- Plan every mapping at boot, or map one large range on first use (the single 64 MB mapping: **UNVERIFIED on the console**).
- Do not take a pass in the emulator as proof for kernel resource limits (handles, mappings, memory blocks): test the worst case on the console.

## Cooperative scheduler: an exited thread must never come back (LEGO)

LEGO runs guest threads one at a time under a turn (a GIL with explicit hand-offs). The title movie ended on a black screen in about 1 run in 5: `KeResumeThread` (or `ResumeThread`) put the player's demux thread back in the rotation after it had exited, and the turn waited for it forever.
- Mark a thread as gone when it leaves, and refuse to add a gone id again (log the refusal: `[SCHED] slot N ... not added again`).
- A watchdog thread that notices the turn not moving while others wait, prints who holds it and hands the turn on, found this in the emulator and is cheap to keep (`[SCHEDWATCH]`, behind a switch). Both pieces, against a minimal scheduler: `tools/sched_watchdog.cpp`.
- Confirmed on the console in run 124: the refusal lines printed and the game went back to the title.

## Finding where a guest thread spends time without a profiler (LEGO)

A host thread that polls a guest thread's context (its `lr` and frame chain) every 20-500 µs is cheap and showed the main thread's trail before a crash, but it missed events that happen within microseconds: a probe inside the code path (an override of a function called from another file) catches them. When the game stalls, a GDB dump of every thread's stack (guide 05) shows which guest thread holds the turn.

## Which cores and threads are busy (RTCW)

Two measures, both in `tools/core_usage.c`:
- **Busy per core.** The kernel gives a core's idle time (`svcGetInfo` `InfoType_IdleTickCount`) only to a thread running on that core. A small thread pinned to each of cores 0-2, at a high priority, wakes once a second and reads it.
- **Every thread of the process.** `-Wl,--wrap=threadCreate` sees every thread anyone creates (SDL, Mesa, newlib's pthreads), with the creating calls from the frame pointer chain; its CPU share comes from `InfoType_ThreadTickCount`. In the emulator this listed SDL's audio thread and showed Mesa had none.

What it showed on the console (RTCW, iortcw's single-threaded engine): the main thread, allowed on any core, did everything and moved between cores 0 and 1; core 2 sat idle. In a scene where frames waited for the GPU, the cores were 15-33 % busy: no CPU work would have helped there. Read busy shares with the CPU clock beside them (guide 07): the same work is about 1.75 times busier at 1020 MHz than at 1785. A second thread (the renderer's back end, as Quake III's SMP mode did) has two free cores to use when the CPU is the limit (**UNVERIFIED**: untried). Core 3 is not one of them when launched the usual way: the process core mask is 0x7 (guide 07). For loads, the other candidate is a reader thread on core 1 that reads the next pk3 blocks while core 0 inflates and parses (**UNVERIFIED**: untried; in RTCW the reads were ~4 s of a 10-13.5 s load at ~19 MB/s).
