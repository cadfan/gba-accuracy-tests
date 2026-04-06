# Contributing to gba-accuracy-tests

Thanks for considering a contribution. There are three things this repo
takes patches for, in roughly this order of urgency:

1. **New runner adapters** — add an emulator to the matrix
2. **New test cases** — add a test ROM (or a new sub-test in an existing manifest)
3. **Fixes to existing scripts, manifests, BIOS handling, dashboard, docs**

This guide covers all three. The submission process is the same: open a
PR against `master`, the GitHub Actions sweep will run on it, and if the
new contribution drops cleanly into the matrix it gets merged.

## Adding a runner adapter

A runner adapter is a small Python file in `runners/` that knows how to
drive one specific emulator's headless mode. Adapters are independent —
adding yours doesn't change anybody else's runner, and missing runners
are skipped at sweep time, never errors.

### The contract

Every runner adapter exposes a module-level `RUNNER` instance with two
methods:

```python
class MyEmulatorRunner:
    name = "my_emulator"

    def is_available(self) -> bool:
        ...

    def run_test(
        self,
        rom_path: Path,
        frames: int,
        output_path: Path,
        *,
        inputs: list[dict] | None = None,
        completion: dict | None = None,
        bios_mode: str = "official",
    ) -> bool:
        ...

RUNNER = MyEmulatorRunner()
```

`is_available()` should return `True` iff your emulator's binary (or
library, or HTTP server, or whatever) is reachable from this machine
right now. The sweep skips runners that aren't available — never raises.

`run_test()` runs one test and writes the captured framebuffer to
`output_path` as **raw BGR555 little-endian bytes, 76800 bytes total**
(240 × 160 × 2). Returns `True` on success. Don't write PNGs — the
diff/dashboard pipeline assumes raw bytes.

#### `inputs`
The manifest's `[[tests.input]]` schedule, expanded by `generate_refs.py`
into press/release pairs (`KEY_HOLD_FRAMES = 10`). Each entry is
`{"frame": int, "keys": int}`. The `keys` field is a GBA KEYINPUT
bitmask (active-high — bit 0 is A, bit 7 is DOWN, etc.), and the entry
means "set the held key mask to this value at this frame and hold it
until the next entry overrides".

#### `completion`
The manifest's `[tests.completion]` table. Supported types:

- `{"type": "exact_frame", "frame": N}`
- `{"type": "stable_frames", "window": W, "min_frames": F}`
- `{"type": "input_then_stable", "window": W, "min_frames": F}`

If your runner can detect framebuffer stability mid-run, honoring the
`stable_frames` mode will produce more semantically correct captures
and shorter run times. If it can't, just run for `frames` frames and
capture the final framebuffer — it's a fine fallback (most existing
runners do this).

#### `bios_mode`
One of `"official"`, `"hle"`, `"cleanroom"`. See [BIOS.md](BIOS.md) for
the full semantics. The short version:

- `official` → load the user-provided real Nintendo BIOS
  (`MGBA_BIOS_PATH` / `NBA_BIOS_PATH` env var or `runners/cores/gba_bios.bin`)
- `cleanroom` → load `runners/cores/gba_bios_cleanroom.bin`
- `hle` → use your emulator's internal HLE BIOS, or fall back to a
  cleanroom BIOS file if your emulator can't truly HLE

Your runner doesn't have to support all three modes — pick what's
sensible for your emulator. Document the choice in the adapter's
docstring; the matrix will just show the modes you handled.

### Discovery convention

Adapters discover their emulator binary via, in order:

1. `MY_EMULATOR_PATH` env var (something like that — pick a name)
2. `runners/cores/my-emulator-binary` (default in-tree drop location)
3. `shutil.which("my-emulator-binary")` (PATH lookup)

`runners/cores/.gitignore` already excludes `*.exe`, `*.dll`, `*.bin`
etc. so users dropping their own emulator binary won't accidentally
commit it.

### Smoke test

Before opening a PR, run:

```bash
python scripts/generate_refs.py --runner my_emulator --suite jsmolka --test jsmolka-arm
python scripts/generate_refs.py --runner my_emulator --suite armwrestler
python scripts/generate_refs.py --runner my_emulator --suite mgba-suite --test mgba-suite-shifter
```

These three exercise the easy CPU test, the input-driven menu navigation,
and the multi-suite manifest. If all three produce hashes (any hashes —
agreement isn't required), you're done. Open the PR.

### Reference adapters to read

- `runners/nanoboyadvance.py` — invoking an external native binary
- `runners/mgba.py` — driving a libretro DLL via ctypes
- `runners/skyemu.py` — talking to an HTTP server
- `runners/cable_club.py` — invoking a Rust binary built from this repo

If your emulator's headless mode doesn't fit any of these patterns,
write whatever subprocess / IPC / FFI logic you need; the framework
only cares about the `run_test()` signature.

## Adding a new test case to an existing suite

1. Edit the suite's `manifest.toml` (e.g., `suites/jsmolka/manifest.toml`).
2. Add a new `[[tests]]` block with `id`, `rom`, `subsystem`, `max_frames`, `[tests.completion]`, and any `[[tests.input]]` events.
3. Run a sweep against the new test: `python scripts/sweep_all.py --suites jsmolka`.
4. Run `python scripts/promote_tiers.py` to label the new test's tier.
5. Commit the manifest, the new entries in `references.json`, and the captured `refs/*.bin` files.

## Adding a brand new test suite

1. Create `suites/<suite_name>/manifest.toml` with a `[suite]` table and at least one `[[tests]]` block.
2. If the ROM is sourceable from a public repo or wiki, add an entry to `scripts/download_roms.py`'s `ROM_MANIFEST`. Use `kind = "github_raw"` for a pinned commit on GitHub, or `kind = "direct"` for an explicit URL list (with optional `#unzip=member.gba` fragment for archive extraction).
3. Drop the ROM at `roms/<suite_name>/...`.
4. Run a sweep. Commit manifest + references + bins.

## License

By submitting a contribution, you agree it's MIT-licensed under the
repo's root `LICENSE` (cadfan, 2026), unless your contribution carries
its own filename-scoped `LICENSE.<thing>` file (the way
`LICENSE.Cult-of-GBA-BIOS` does).

Don't submit third-party emulator binaries or proprietary ROMs.
Pre-built binaries belong in `runners/cores/` (which is gitignored)
and the user drops them in themselves; ROMs that aren't freely
distributable belong in nobody's repo.
