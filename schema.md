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
  "schema_version": 2,
  "references": {
    "test-id": [
      {
        "hash": "sha256-hex-64-chars",
        "tier": "gold",
        "bios_mode": "official",
        "note": "optional note",
        "provenance": {
          "emulator": "NanoBoyAdvance",
          "version": "1.8.2",
          "commit": "abc123...",
          "bios_mode": "official",
          "bios_sha256": "sha256-of-bios-file",
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

### BIOS Modes

Each reference is tagged with the BIOS mode used during capture:

- **`official`**: Nintendo's official GBA BIOS (SHA256: `300c20df6731a33952ded8c436f7f186d25d3492860571b21d43c2e8b3c4deaf`)
- **`hle`**: High-level emulation of BIOS functions (emulator-specific)
- **`skip`**: BIOS skipped entirely, direct jump to ROM entry point
- **`cleanroom`**: Open-source cleanroom BIOS implementation (e.g., Normatt's)

**Comparison rule:** `compare.py` and the Rust harness only compare hashes within the same BIOS mode. A reference captured under `official` BIOS will NOT match a test run under `hle`, even if the hash is identical. This prevents false passes where different BIOS modes produce the same framebuffer by coincidence.

**Migration from schema_version 1:** References without `bios_mode` are treated as `"hle"` (the historical default). Tools should auto-migrate on read.

### Reference Tiers

- **gold**: Hardware-verified or from a 100%-passing emulator for this suite
- **secondary**: From a trusted emulator with known limitations
- **candidate**: Unverified, submitted by community

### Oracle Selection

Per-suite gold standard emulator, used when references disagree:

1. Hardware-verified captures (if available)
2. GBAHawk (highest overall pass rate)
3. Mesen > NanoBoyAdvance > mGBA (tiebreaker order)

**Contested:** Multiple oracle-tier emulators produce different hashes for the same test + BIOS mode. Indicates unknown hardware behavior.

**Unverified:** No emulator passes the test under any BIOS mode.

### Provenance Fields

- `emulator`: Name of the emulator that generated this reference
- `version`: Emulator version string
- `commit`: Git commit SHA of the emulator (for reproducibility)
- `bios_mode`: One of `official`, `hle`, `skip`, `cleanroom`
- `bios_sha256`: SHA256 of BIOS file used, or `null` for HLE/skip
- `rom_sha256`: SHA256 of the ROM binary (cross-checks manifest)
- `frame_count`: Number of frames run before capture
- `captured_at`: ISO 8601 timestamp
- `captured_by`: Username or "generate_refs.py"

### Reference Framebuffers

Raw BGR555 framebuffers (.bin, 76800 bytes) are stored alongside references for diff image generation:

```
suites/<name>/refs/<emulator>-<bios_mode>-<test_id>.bin
```

These files enable diff triptych generation (Expected | Actual | Diff) on test failure.

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
  "schema_version": 2,
  "runner": "mgba",
  "suite": "jsmolka",
  "bios_mode": "official",
  "timestamp": "2026-04-04T12:00:00+00:00",
  "summary": {"pass": 4, "fail": 2, "skip": 0, "error": 0},
  "results": [
    {
      "test_id": "jsmolka-arm",
      "status": "PASS",
      "actual_hash": "abc123...",
      "matched_reference": {
        "hash": "abc123...",
        "tier": "gold",
        "emulator": "NanoBoyAdvance"
      },
      "time_s": 1.2
    },
    {
      "test_id": "jsmolka-thumb",
      "status": "FAIL",
      "actual_hash": "def789...",
      "expected_hashes": ["def456..."],
      "time_s": 0.9
    }
  ]
}
```

### Results Fields

- `bios_mode`: The BIOS mode used for this run (determines which references to compare against)
- `matched_reference`: On PASS, which specific reference was matched (tier + source emulator)
- `actual_hash`: SHA256 of the captured framebuffer (always included)

Status values: PASS, FAIL, CRASH, TIMEOUT, ERROR, SKIP.

Exit codes: 0 = all pass, 1 = any fail/crash, 2 = error.

### Test Annotations

Tests may have annotations in the manifest that affect scoring:

- `requires_hardware = true`: Test needs physical link cable. Excluded from default scoring.
- `caveat = "string"`: Test has known issues (e.g., flash tests that fail on real hardware). Scored separately.
- `unverified_subtests = N`: Only N of M subtests have emulator consensus. Score only consensus subtests.
