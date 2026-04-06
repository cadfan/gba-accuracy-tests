# BIOS modes

This repo runs every test under three different BIOS configurations so you
can see which differences are emulator divergences and which are just BIOS
divergences. Pick the column you care about, depending on what you have
on hand and what you're testing.

| Mode         | What loads onto the bus                  | Distributable?  | Why use it                                     |
|--------------|------------------------------------------|-----------------|------------------------------------------------|
| `official`   | The user-provided real Nintendo GBA BIOS | ❌ No (Nintendo IP) | Highest fidelity for tests that exercise SWI handlers, BIOS arithmetic, RNG seed, boot animation. Required for AGS Aging Cartridge accuracy. |
| `hle`        | The emulator's own internal HLE BIOS     | ✅ Yes          | What end-users without a real BIOS dump will hit. Tests that emulators have correctly implemented the documented BIOS surface. |
| `cleanroom`  | The Cult-of-GBA replacement BIOS         | ✅ Yes (MIT)    | A real 16 KB BIOS blob on the bus, but freely redistributable. Lets users run the full suite out of the box, without sourcing a Nintendo dump. |

## How each runner reads each mode

Different emulators expose BIOS configuration through different mechanisms.
This table documents what actually happens when you set `--bios-mode X`
for each runner.

|                     | `cable_club`                                  | `mgba` (libretro)                              | `nanoboyadvance`                              | `skyemu`                                              |
|---------------------|-----------------------------------------------|------------------------------------------------|-----------------------------------------------|-------------------------------------------------------|
| `official`          | `--bios <Nintendo>`. Boots through the BIOS animation. | Real BIOS placed in the libretro system dir.   | `--bios <Nintendo>` (no `--skip-bios`).       | Real BIOS copied next to the ROM as `gba_bios.bin`.   |
| `hle`               | `--skip-bios`. cable_club's internal HLE.     | No BIOS file shipped — mgba's built-in HLE.    | `--bios <Nintendo> --skip-bios` (NBA needs the data for SWI dispatch even when skipping the boot animation; there is no true HLE in NBA). | No sibling file — SkyEmu falls back to its **internal** Cult-of-GBA BIOS. |
| `cleanroom`         | `--bios <Cult-of-GBA>`. Real BIOS on the bus, MIT-licensed. | Cult-of-GBA BIOS placed in the libretro system dir. | `--bios <Cult-of-GBA>`. Real BIOS on the bus. | Same as `hle` — SkyEmu validates external BIOS files against the Nintendo hash and rejects non-canonical blobs, so we use SkyEmu's internal Cult-of-GBA fallback instead. |

NBA's `hle` and `cleanroom` modes look almost identical (both load a real
BIOS file), but they differ in *which* BIOS file. NBA's `--skip-bios` flag
skips the boot animation regardless of which BIOS is loaded, so the
accuracy difference between modes is whether the SWI handlers come from
Nintendo or from Cult-of-GBA.

SkyEmu's `hle` and `cleanroom` modes are equivalent by design — its
internal fallback BIOS *is* Cult-of-GBA. Documenting both modes for
SkyEmu keeps the matrix uniform across runners.

## Where the BIOS files live

```
runners/cores/
  gba_bios.bin                          # ❌ gitignored. User-provided. 16384 bytes.
                                         #    Drop your own dump here. Canonical
                                         #    Nintendo sha256: fd2547724b505f487e6dcb29ec2ecff3af35a841a77ab2e85fd87350abd36570
  gba_bios_cleanroom.bin                # ✅ committed. 16384 bytes. Cult-of-GBA.
                                         #    sha256: 61af6e8c2db6cf24aa6924e8133f6a50833158fca33ff08ea5e11e1a06e132f2
  gba_bios_cleanroom.sha256             # ✅ committed. Pinned hash.
  gba_bios_cleanroom.commit             # ✅ committed. Pinned upstream commit.
  LICENSE.Cult-of-GBA-BIOS              # ✅ committed. MIT license text. Attributes
                                         #    DenSinH and fleroviux exclusively for that file.
```

The submodule's root `LICENSE` (MIT, cadfan) covers the rest of the
project — runners, manifests, scripts, dashboard. The Cult-of-GBA
license is filename-scoped so there's no ambiguity about who owns what.

## How to provide a Nintendo BIOS

Drop a 16384-byte `gba_bios.bin` at `runners/cores/gba_bios.bin`. It's
gitignored. The runners pick it up via:

- `MGBA_BIOS_PATH` environment variable, or
- `NBA_BIOS_PATH` environment variable, or
- `runners/cores/gba_bios.bin` (the default location)

If you're paranoid about hash, the canonical Nintendo dump matches:

```
sha256: fd2547724b505f487e6dcb29ec2ecff3af35a841a77ab2e85fd87350abd36570
md5:    a860e8c0b6d573d191e4ec7db1b1e4f6
```

We don't ship Nintendo BIOS, we don't auto-download Nintendo BIOS,
and we don't ask. If you don't have one, use `cleanroom` mode — it works
identically for ~95% of tests.

## How to (re-)bootstrap the cleanroom BIOS

It's already in the repo, but if you want to redownload it from upstream:

```bash
python scripts/download_roms.py --bios-only
```

This pulls `bios.bin` from the pinned upstream commit
`a30e9a96df083628b650724b7d4d7112b4070b98` of
[Cult-of-GBA/BIOS](https://github.com/Cult-of-GBA/BIOS), verifies the
SHA256, and drops it at `runners/cores/gba_bios_cleanroom.bin`.

## When official and cleanroom diverge

The dashboard surfaces this directly: any test where the cross-runner
consensus hash under `official` differs from the consensus under
`cleanroom` is a real BIOS-implementation difference. Look at the
tests that diverge to learn which BIOS surface area Cult-of-GBA hasn't
matched yet — it's a useful signal both for emulator authors and for
people working on cleanroom BIOS implementations.

The most common reason for divergence is that AGS Aging Cartridge
exercises BIOS handlers (decompression, math, RNG) that Cult-of-GBA
hasn't fully implemented. jsmolka-bios is another one — it specifically
probes BIOS behaviour and you'd expect it to differ.
