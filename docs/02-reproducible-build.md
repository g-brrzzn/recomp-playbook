# Reproducible build

## Docker with pinned versions (Manhunt)

The Manhunt build runs in two images:
1. **Recompiler:** Python 3.12 with exact capstone and unicorn versions, and xboxrecomp at a fixed commit. This is where x86 becomes C.
2. **devkitA64 pinned by digest** (`devkitpro/devkita64@sha256:...`): exactly the same GCC, libnx and Mesa as the project owner's.

What it gives:
- The first clean build on Windows worked at once and matched the owner's, without installing Python or a compiler.
- `docker run --network none`: game data never leaves the machine.
- The same recipe works on Windows, Linux and Mac.

What it costs:
- Docker Desktop's VM had 7.3 GB. With 12 jobs, the huge generated C files ran it out of memory: use 4 (`CPUS=4`). The clean build took ~10 minutes.
- Reading Windows files through the VM is slower.
- Docker Desktop stopped when the PC went to sleep: restart it before blaming the build.

## Native toolchain (LEGO)

LEGO builds with native devkitPro on Windows (MSYS2), with at most 2 jobs (start with 1). A clean build of the game code takes ~47 minutes with 2 jobs.

Gaps found in the first clean build on another machine (worth checking in any build guide):
- submodules missing from the list;
- devkitPro packages Meson asks for (zlib, expat);
- `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` with CMake 4;
- the devkitPro updater's silent mode exits with 0 and installs nothing;
- an unanchored `.gitignore` entry (`XenonRecomp/` instead of `/XenonRecomp/`) that hid a licence file.

## Checking the build is the same

- A hash of each input (game executable, image, header) against an expected list.
- In LEGO: 3,166 of 3,166 generated files matched the reference hashes, before compiling.
- An NRO of the same size with a different hash proves nothing by itself: the build path can end up in the binary. Investigate before concluding.

## Line endings on Windows

`core.autocrlf=true` turns `.sh` scripts into CRLF, and they stop running inside Linux. Before the first checkout:

```
git config core.autocrlf false
git config core.eol lf
```

If already cloned, check out again after changing them.

## Changing one file's options does not recompile it

With CMake and the Makefile generator, changing one file's `COMPILE_OPTIONS` (for example `-O3` on a single file) does not rebuild that object. Delete the `.o` or use a new build folder. In Manhunt this made one measurement compare a binary with itself. At least it measured the noise.
