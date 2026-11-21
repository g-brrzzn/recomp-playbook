# PGO in a Switch homebrew

PGO (profile-guided optimization): build a version that counts which paths the code takes, play with it, then rebuild using those counts. The compiler then separates hot and cold code and makes better inlining choices.

## Results

| Port | Training | Result |
|---|---|---|
| LEGO | One console session, ~10 min, handheld at 460.8 MHz | **Main thread ~11 % faster**: 140 ns per call against 157 ns at the same clock. Heavy frames (1,300+ draws): +11.4 % speed (90 % interval: −30.7 to −0.6 % frame time). Medium frames: no measurable change (probably GPU-limited). Became the default build |
| Manhunt | Emulator: three 4-minute runs (the two heaviest levels and the first mission) | Final build with no missing-profile warning; code 22.56 → 21.45 MB. **Speed UNVERIFIED**, and it is unknown whether a profile taken in the emulator steers the compiler as well as a console one |

## Why the usual PGO does not work

libgcov writes the `.gcda` files at program exit, assuming a PC file system. On the Switch the game usually ends from HOME, and that exit path never runs.

## How

### 1. Build the counting version

```
-fprofile-generate -fprofile-update=single -fno-profile-values -fprofile-info-section=gcov_info
```

- `-fprofile-info-section=gcov_info`: each object registers its counters in a section instead of relying on the exit path.
- `-fprofile-update=single`: counters without atomics (faster; loses some counts across threads, which is acceptable).
- `-fno-profile-values`: no value profiling, which is heavy and of little use here.

The counting build is much slower (LEGO: 227 ns per call against 151). Do not measure FPS with it.

### 2. Stream the counters to the SD card while playing

`tools/pgo_stream.c` walks the `gcov_info` section and writes everything with `__gcov_info_to_gcda()` into a `.stream` file:
- a thread writes periodically (Manhunt: every 60 s; LEGO: every 3 min), and at exit when the exit runs;
- counters only grow, so the last snapshot of a session holds all of it; each snapshot replaces the previous one (written to a `.tmp`, then renamed);
- in Manhunt, a snapshot took ~70 ms.

### 3. Merge on the PC

`tools/pgo_merge.py`:
1. runs `aarch64-none-elf-gcov-tool merge-stream` on each `.stream` (inside the same devkitA64 image as the build);
2. **fixes each `.gcda`'s summary:** the stream path leaves `runs = 0` and `sum_max = 0`, and GCC derives its hot threshold from `sum_max`. With 0, every block counts as hot. The script sets `runs` to the number of sessions and `sum_max` to the largest arc count across all objects.

### 4. Build the optimized version

```
-fprofile-use -fprofile-correction -fprofile-partial-training -fno-profile-values
```

- `-fprofile-correction`: tolerates the inconsistent counts from `-fprofile-update=single`.
- `-fprofile-partial-training`: code the training never reached is optimized normally, not as cold.

## Pitfalls met

- **The profile folder must exist** before `merge-stream`, or it skips every object ("Skip") without an error.
- **Merging twice adds the counts.** Run it on an empty profile folder.
- **Same path in both builds.** Each `.gcda` name comes from the object's path in the counting build. In Manhunt, both builds use the same path inside the container, so nothing needs renaming.
- **Long paths on Windows (LEGO):** 9 `.gcda` names were over 259 characters, and Windows tools do not write them. Fix: a short profile folder, and the names rewritten in a copy of the stream before `merge-stream`.
- **Thread priority (LEGO):** the first version created the thread at priority 0x3F, which is not allowed. The thread never ran, and no file reached the card in 31 minutes. 0x3B is the lowest allowed. Log the creation result.
- **The profile ages:** changed functions lose their counts ("coverage mismatch" warnings). Train again after large changes, and do PGO last, after the generated-code changes.
- **Code grows:** in LEGO, 103.6 → 109.8 MB, and one object went from 8 to 104 hot/cold sections. That is normal.
