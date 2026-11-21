# Licences

## What never goes in here

- Game files, BIOS, keys, firmware and saves.
- C code generated from a game's executable: it is derived from the game.
- Memory captures, shader packs, SDK or compiler binaries.
- Personal paths, accounts, other repositories' history.

## Code from other projects

The tools here were written for these ports and rewritten in generic form, under this repository's licence (MIT, see `LICENSE`). The ports themselves use third-party code under its own licences:

| Project | Licence | Used in |
|---|---|---|
| xboxrecomp (recompiler, runtime, kernel) | MIT; the audio emulator (`src/apu/`, from xemu) is LGPL-2.1+ | Manhunt |
| OpenGL NV2A renderer from the Burnout 3 Switch port | MIT | Manhunt |
| XenonRecomp | see its `LICENSE.md` | LEGO |
| The LEGO port's upstream repository | CC BY-NC-SA 4.0 | LEGO |

When copying a piece of any of them elsewhere, follow its licence and keep the credit. When in doubt, rewrite the technique and cite where it came from.
