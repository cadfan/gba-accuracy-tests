# gba-accuracy-tests

Automated accuracy testing for GBA emulators. Test ROM manifests, reference hashes, diff images.

Any GBA emulator (C, C++, Rust, Go) can use this to measure accuracy: run ROMs headlessly, produce screenshots, compare against references.

## Quick Start

```bash
git clone https://github.com/cadfan/gba-accuracy-tests
cd gba-accuracy-tests
pip install -e .                                     # or: pip install Pillow tomli
python scripts/download_roms.py                      # Download test ROMs (~15 MB)
python compare.py run --runner mgba --suite jsmolka  # Run and compare
```

## Adding Your Emulator

**Option 1: Write a runner adapter (recommended)**

Copy `runners/TEMPLATE.py` to `runners/my_emulator.py`. Implement `run_test()` and `is_available()`. Then:

```bash
python compare.py run --runner my-emulator --suite jsmolka
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

**Option 2: CLI command template (for emulators with existing headless mode)**

If your emulator already supports headless screenshots:

```bash
python compare.py run --command my-emu --headless {rom} --frames {frames} --screenshot {output} --suite jsmolka
```

Placeholders `{rom}`, `{frames}`, `{output}` are substituted per test. Most emulators will need a runner adapter instead, since this convention is not universal.

## Test Suites

| Suite | Tests | Source | Notes |
|-------|-------|--------|-------|
| jsmolka | 6 | [jsmolka/gba-tests](https://github.com/jsmolka/gba-tests) | ARM, Thumb, BIOS, memory, edge cases |
| armwrestler | 1 | [destoer/armwrestler-gba-fixed](https://github.com/destoer/armwrestler-gba-fixed) | ARM instruction visual grid. Requires START button. |
| mgba-suite | 0 (v2) | [mgba-emu/suite](https://github.com/mgba-emu/suite) | Timing, DMA, timer. Placeholder for v2. |

Download size: ~15 MB total.

## Available Runners

| Runner | Emulator | Status |
|--------|----------|--------|
| `mgba` | [mGBA](https://mgba.io/) | Requires mGBA + Lua scripting |
| `cable-club` | [Cable Club](https://github.com/cadfan/cable-club) | Requires accuracy-sweep binary |

## Reference Hashes

References are stored as SHA256 hashes of raw BGR555 little-endian framebuffer bytes (240x160 u16 values, 76800 bytes total). Each reference includes full provenance: emulator name, version, commit, BIOS mode, ROM checksum, frame count, and capture timestamp.

**V1 references** are from mGBA 0.10. mGBA is known-bad on jsmolka ARM test 235 and Thumb test 230. NanoBoyAdvance (gold standard, 100% jsmolka pass rate) references are planned for v2.

See [schema.md](schema.md) for the full reference format specification.

**Important for test runs:** Disable color correction in your emulator. Color correction LUTs change pixel values and produce different hashes.

## Capture Point

Framebuffers are captured at **VBlank start (scanline 160)**, immediately after the PPU finishes rendering all 160 visible scanlines. This is when the framebuffer is complete and stable.

## How It Works

1. `compare.py run` loads TOML manifests from `suites/*/manifest.toml`
2. For each test: runner executes the ROM for N frames, saves a screenshot
3. Screenshot is converted to BGR555 raw bytes and SHA256-hashed
4. Hash is compared against all valid references in `suites/*/references.json`
5. PASS if the hash matches any reference (gold or secondary tier)
6. FAIL produces a diff triptych image (Expected | Actual | Diff)

## BIOS Requirements

Most test ROMs work with HLE (built-in) BIOS. The `jsmolka-bios` test depends on BIOS implementation details and may produce different hashes with different HLE implementations. The manifest `requires_bios` field indicates when a real BIOS is needed.

## License

MIT for tooling. Test ROM suites have their own licenses, see [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md).
