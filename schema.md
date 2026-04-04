# Schema Reference

## Manifest Format (TOML)

Each suite has a `suites/<name>/manifest.toml`:

```toml
schema_version = 1

[suite]
name = "string"          # Suite identifier
description = "string"   # Human-readable description
source = "url"           # Upstream repository URL
commit = "sha"           # Pinned commit SHA

[[tests]]
id = "string"            # Unique test identifier (used in results and references)
rom = "path"             # ROM filename relative to roms/<suite>/
rom_sha256 = "hex64"     # SHA256 of the ROM binary
subsystem = "string"     # Freeform: cpu-arm, cpu-thumb, bios, memory, ppu, timer, dma, misc
max_frames = 600         # Safety timeout (maximum frames to run)
timing_sensitive = false # True for tests where emulators may legitimately diverge
requires_bios = false    # True if a real GBA BIOS is needed
bios = "skip"            # Optional: "skip", "hle" (default), or path to BIOS
hint = "string"          # Optional: debugging hint shown on failure

[tests.completion]
type = "stable_frames"   # Completion detection strategy (see below)
window = 10              # Consecutive frames with identical hash
min_frames = 30          # Minimum frames before checking stability
```

### Completion Strategies

- **`stable_frames`**: Capture when the framebuffer hash is identical for `window` consecutive frames after `min_frames`. Default for most test ROMs.
- **`exact_frame`**: Capture at frame N (`frame = 120`). For animated or non-stabilizing ROMs.
- **`debug_string`**: Wait for a substring in `REG_DEBUG_STRING` (0x04FFF600). mGBA extension.
- **`input_then_stable`**: Inject input, then wait for stabilization. For ROMs needing button presses.

`max_frames` is the safety cap for all strategies. Simple runners that don't support per-frame hashing just run for `max_frames`.

### Input Injection

```toml
[[tests.input]]
frame = 5      # Frame number to inject input
keys = 8       # GBA KEYINPUT bitmask (active-high)
```

GBA KEYINPUT bits: A=0, B=1, SELECT=2, START=3, RIGHT=4, LEFT=5, UP=6, DOWN=7, R=8, L=9.

## References Format (JSON)

Each suite has a `suites/<name>/references.json`:

```json
{
  "schema_version": 1,
  "references": {
    "test-id": [
      {
        "hash": "sha256-hex-64-chars",
        "tier": "gold",
        "note": "optional note",
        "provenance": {
          "emulator": "NanoBoyAdvance",
          "version": "1.8.2",
          "commit": "abc123...",
          "bios": null,
          "rom_sha256": "sha256-of-rom",
          "frame_count": 120,
          "captured_at": "2026-04-04T00:00:00Z",
          "captured_by": "username"
        }
      }
    ]
  }
}
```

### Reference Tiers

- **gold**: Hardware-verified or from a 100%-passing emulator (e.g., NanoBoyAdvance)
- **secondary**: From a trusted emulator with known limitations (e.g., mGBA)
- **candidate**: Unverified, submitted by community

`compare.py` reports PASS if the actual hash matches ANY reference (any tier).

### Provenance Fields

- `emulator`: Name of the emulator that generated this reference
- `version`: Emulator version string
- `commit`: Git commit SHA of the emulator (for reproducibility)
- `bios`: SHA256 of BIOS file used, or `null` for HLE/built-in
- `rom_sha256`: SHA256 of the ROM binary (cross-checks manifest)
- `frame_count`: Number of frames run before capture
- `captured_at`: ISO 8601 timestamp
- `captured_by`: Username or "generate_refs.py"

## BGR555 Format

GBA hardware uses BGR555: 16-bit pixels, little-endian.

```
Bit layout: [15] unused | [14:10] Blue | [9:5] Green | [4:0] Red
```

Conversion from 8-bit RGB:
```python
r5 = (r8 >> 3) & 0x1F
g5 = (g8 >> 3) & 0x1F
b5 = (b8 >> 3) & 0x1F
u16 = r5 | (g5 << 5) | (b5 << 10)
```

Reference hashes are SHA256 of 76,800 bytes (240 x 160 x 2), packed as little-endian u16.

## Results Format (JSON)

Output of `compare.py run`:

```json
{
  "schema_version": 1,
  "runner": "mgba",
  "suite": "jsmolka",
  "timestamp": "2026-04-04T12:00:00+00:00",
  "summary": {"pass": 4, "fail": 2, "other": 0},
  "results": [
    {
      "test_id": "jsmolka-arm",
      "status": "PASS",
      "time_s": 1.2
    },
    {
      "test_id": "jsmolka-thumb",
      "status": "FAIL",
      "actual_hash": "abc123...",
      "expected_hashes": ["def456..."],
      "time_s": 0.9
    }
  ]
}
```

Status values: PASS, FAIL, CRASH, TIMEOUT, ERROR, SKIP.

Exit codes: 0 = all pass, 1 = any fail/crash, 2 = error.
