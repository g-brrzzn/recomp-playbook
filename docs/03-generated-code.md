# Changes to the generated C

The recompiler generates thousands of C functions (Manhunt: 60 files, 14,800 functions). Whatever each function does to reach the original console's memory and registers repeats millions of times, so a small cost per access adds up.

## How to change it: a reversible step after the recompiler (Manhunt)

Instead of changing the recompiler, a script edits the generated files right after it runs (`tools/post_lift.py`, generic version):
- each edit leaves a **mark** (`/* post-lift: regs */`), so it can be taken out later;
- `--undo` restores each file **byte for byte** as the recompiler wrote it, and a test checks that;
- each edit has an environment switch to leave it out;
- only files that change are rewritten, so incremental builds recompile only what is needed;
- new names (`_plr`, `_plmb`) must not clash with names the recompiler already uses. In Manhunt, `_r` was taken and the build broke.

The test (`tests/test_post_lift.py`) covers applying, applying again (no change), each edit alone, byte-exact undo, and a negative control (a file without the pattern stays the same).

## Memory base in a local (Manhunt)

**Problem:** every guest memory access computes `address + g_xbox_mem_offset`, a global. The accesses are `volatile` and the code is built with `-fno-strict-aliasing`, so the compiler reloads the global from memory before almost every access: two dependent loads per access.

**Fix:** the base is written only at boot, before the game starts. So each function reads it once:
```c
const uintptr_t _plmb = (uintptr_t)g_xbox_mem_offset;
```
and each file redefines the access macro to use `_plmb`.

**Measured:** −5.3 % instructions in one generated file; total code −3.9 %. **Console speed: UNVERIFIED.**

## Guest registers in one block (Manhunt)

**Problem:** the runtime kept each x86 register (`eax`, `ecx`, ...) as its own thread-local. With `-mtp=soft`, every function calls `__aarch64_read_tp` and ties up one ARM register per TLS address.

**Fix:**
- a single TLS block, `g_guest_regs`, written in assembly (`.tbss`), with the old names as aliases inside it (`.set g_eax, g_guest_regs + 4`). Runtime code that uses the old names keeps working unchanged;
- each function takes one pointer (`RecompGuestRegs *const _plr = &g_guest_regs;`), and macros turn `eax` into `_plr->r_eax`;
- a runtime patch (`#ifndef RECOMP_GUEST_REGS_EXTERNAL`) removes the old definitions;
- `_Static_assert` checks every offset between the C and the assembly.

**Measured (both changes together):**
- one generated file: 83,314 → 63,401 instructions (−24 %);
- total code: 25.85 → 22.56 MB (−12.7 %);
- emulator: 11 levels, 19.5 min per build, no hang, no new error, the same images; game-thread CPU went from 76 % to 73 % (a weak hint).

**Console speed: UNVERIFIED.**

This does not apply to LEGO: XenonRecomp already passes the base as a parameter (`PPC_FUNC(x)` is `void x(PPCContext& ctx, uint8_t* base)`) and already keeps registers as C++ locals (`non_argument_as_local` and related options in the `.toml`).

## Addressing without a region table, and float compares (LEGO)

A sampling profile on the console showed that the cost sat in two patterns of the generated code, not in the functions themselves:
- **16.6 %** of game-code samples landed right after a load from a region table, done before every memory access. The "fast fold" (`--fold-fast`) removed the table. It is exact while a heap shortcut stays off; a build with the shortcut on refuses to start.
- **3.0 %** in float compares generated as `fcmp` + branch + `fcmpe`. Replaced with a shorter exact form.

**Measured on the console:** 152 ns per game-function call, against 158 ns twice the same day (~−4 % main-thread CPU). Made the default.

## Vector operations the recompiler left empty (LEGO)

XenonRecomp leaves some VMX operations empty: just a `// op` comment followed directly by another comment or a label. LEGO had ~8,600. A script finds them by that pattern and fills them in (`fill_tcs360_movie_ops.py`, with its own test). They caused part of the intro movie's corruption.

With any recompiler: look for operations the generator emits empty or as comments before debugging behaviour.

## Guard patches with fixed address ranges are a trap (LEGO)

Early in the port, the game's heap code got hand-written guards in the generated files: skip a free-list unlink, or a call, when a pointer is outside 0x80000000 (or 0x82000000) to 0x94000000, "garbage from a dump". They encode the runtime's memory map of the day. When the map changed (log134):
- a heap segment placed at 0x816xxxxx (the 0x80 view of a physical block) passed the game's own logic but failed the guard, so the heap silently skipped unlinks; its lists broke, and a later allocation followed a bad link. The crash was far from the cause;
- the same assumption sat in 70 guards over 6 generated files and in 75 checks in the runtime.

What helped:
- one header with the ranges as helpers (`lsw_gptr80(a)`, `lsw_gptr82(a)`, `lsw_vext_ptr(a)`) and a script that rewrites the checks to them, only where the same expression sits on both sides (`X < 0x80000000u || X >= 0x94000000u` → `!lsw_gptr80(X)`), idempotent, adding the include after the file's first `#include` (a later one may sit inside an `#ifdef`);
- running it on both copies of the generated code (LEGO keeps the recompiler's output and a non-volatile copy, neither in Git) and after every regeneration;
- leaving checks with only an upper bound alone (they already accept lower addresses), and reviewing the remaining shapes by hand (kernel-object checks up to 0xC0000000 or 0xE0000000).

Better still: make a guard log when it fires. A silent skip hid this bug for a long time.

## `-Os` for the generated code (Manhunt)

- Code: 22.56 → 19.64 MB (−24 % against the original build).
- One file compiled by hand: 56,427 → 47,550 instructions.
- Emulator: no new error.
- The Cortex-A57 has a 48 KB instruction cache, so smaller code *may* be faster. **UNVERIFIED on the console.** Kept as an option, off.

## `-O3` on the audio mixer only (Manhunt)

- GCC vectorised 14 loops instead of 6, including the mix and the HRTF convolution.
- No `-ffast-math`, and `-ffp-contract=off`: no float operation is reordered or fused, so the output is **bit-exact by construction**.
- Object: 22,339 → 38,041 bytes.
- The emulator cannot show the effect (noise of 419 to 448 ms/s). Option off; **UNVERIFIED on the console**.

## Hot functions together (LEGO)

A linker script (`hot_order.ld`) places the 2,042 most-sampled functions in 3.7 MB of contiguous code, for the instruction TLB. Its gain alone was not measured. PGO does something similar by itself (`.text.hot` sections).

## Watch out: `-ffp-contract` (LEGO)

Without `-ffp-contract=off`, GCC may fuse a separate guest `fmul` and `fadd` into one FMA, which the original console would round twice. But XenonRecomp writes PowerPC's `fmadd` as `a * b + c` (9,019 sites), which is only fused because of that same default. The right fix is `fma()` for the fused forms **and** `-ffp-contract=off` for the rest. It changes game arithmetic, so it needs its own test. Found, not applied.

## Tried, no gain

| Idea | Port | Result |
|---|---|---|
| Guest stack accesses without `volatile` | Manhunt | −0.65 % instructions in one file. With `-fno-strict-aliasing`, any store through a pointer may hit the stack and the register block, so the compiler keeps reloading. Dropped for the risk |
| Guest memory without `volatile` | LEGO | Wrong behaviour in run 78, because the game code lacked `-fno-strict-aliasing`. Shelved; a redo needs that flag |
| 2 MB pages for guest memory | LEGO | 158 ns per call against 155–163 before: no visible gain |
| Inlinable calls between game functions | LEGO | 156–161 ns per call either way |
| `-O3` and byte reversal with a single `TBL` | LEGO | 151 against 152 ns: no measurable change. Kept because they are exact |
| ZCULL in the driver | LEGO | Exact, no gain (see guide 07) |
