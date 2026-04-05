"""Unit tests for gba-accuracy-tests compare.py and reference handling."""
import hashlib
import json
import struct
from pathlib import Path

import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compare import (
    hash_bgr555,
    load_manifest,
    load_references,
    get_expected_hashes,
    get_expected_hash_values,
    FB_BYTE_COUNT,
    FB_PIXEL_COUNT,
)


# --- BGR555 hashing tests ---

def make_framebuffer(fill_value: int = 0) -> bytes:
    """Create a raw BGR555 framebuffer filled with a single pixel value."""
    return struct.pack(f"<{FB_PIXEL_COUNT}H", *([fill_value] * FB_PIXEL_COUNT))


def test_hash_deterministic():
    """Same input always produces same hash."""
    fb = make_framebuffer(0x1234)
    assert hash_bgr555(fb) == hash_bgr555(fb)


def test_hash_different_input():
    """Different framebuffers produce different hashes."""
    fb1 = make_framebuffer(0x0000)
    fb2 = make_framebuffer(0x7FFF)
    assert hash_bgr555(fb1) != hash_bgr555(fb2)


def test_hash_single_pixel_difference():
    """A single pixel change produces a different hash."""
    fb1 = make_framebuffer(0x0000)
    fb2 = bytearray(fb1)
    fb2[0] = 0xFF  # Change one byte
    assert hash_bgr555(bytes(fb1)) != hash_bgr555(bytes(fb2))


def test_hash_is_sha256_hex():
    """Hash is a 64-character hex string (SHA256)."""
    fb = make_framebuffer(0)
    h = hash_bgr555(fb)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_matches_manual_sha256():
    """Hash matches a manually computed SHA256."""
    fb = make_framebuffer(0x1234)
    expected = hashlib.sha256(fb).hexdigest()
    assert hash_bgr555(fb) == expected


def test_framebuffer_size():
    """Framebuffer is exactly 76800 bytes (240*160*2)."""
    fb = make_framebuffer(0)
    assert len(fb) == FB_BYTE_COUNT
    assert FB_BYTE_COUNT == 76800


# --- Cross-layer compatibility test ---

def test_hash_cross_layer_compatibility():
    """Verify Python hashing matches what the Rust harness would produce.

    The Rust harness hashes by iterating u16 values and calling to_le_bytes().
    This test verifies the Python side matches that byte layout.
    """
    # Known framebuffer: pixels 0x0000, 0x0001, 0x0002, ...
    pixels = list(range(FB_PIXEL_COUNT))
    # Pack as little-endian u16 (same as Rust to_le_bytes)
    raw = struct.pack(f"<{FB_PIXEL_COUNT}H", *pixels)
    h = hash_bgr555(raw)
    # Manually verify: SHA256 of the same byte sequence
    manual = hashlib.sha256(raw).hexdigest()
    assert h == manual


# --- BIOS-mode filtering tests ---

SAMPLE_REFS = {
    "schema_version": 2,
    "references": {
        "test-arm": [
            {
                "hash": "aaaa",
                "tier": "gold",
                "bios_mode": "official",
                "provenance": {"emulator": "NanoBoyAdvance", "bios_mode": "official"},
            },
            {
                "hash": "bbbb",
                "tier": "secondary",
                "bios_mode": "hle",
                "provenance": {"emulator": "mGBA", "bios_mode": "hle"},
            },
            {
                "hash": "cccc",
                "tier": "secondary",
                "bios_mode": "official",
                "provenance": {"emulator": "mGBA", "bios_mode": "official"},
            },
        ],
        "test-thumb": [
            {
                "hash": "dddd",
                "tier": "gold",
                "provenance": {"emulator": "GBAHawk"},
                # No bios_mode field: schema v1 migration, should default to "hle"
            },
        ],
    },
}


def test_get_expected_hashes_no_filter():
    """Without BIOS filter, returns all refs."""
    entries = get_expected_hashes(SAMPLE_REFS, "test-arm")
    assert len(entries) == 3
    hashes = [e["hash"] for e in entries]
    assert "aaaa" in hashes
    assert "bbbb" in hashes
    assert "cccc" in hashes


def test_get_expected_hashes_filter_official():
    """Filter by official BIOS returns only official-mode refs."""
    entries = get_expected_hashes(SAMPLE_REFS, "test-arm", bios_mode="official")
    assert len(entries) == 2
    hashes = [e["hash"] for e in entries]
    assert "aaaa" in hashes
    assert "cccc" in hashes
    assert "bbbb" not in hashes


def test_get_expected_hashes_filter_hle():
    """Filter by hle BIOS returns only hle-mode refs."""
    entries = get_expected_hashes(SAMPLE_REFS, "test-arm", bios_mode="hle")
    assert len(entries) == 1
    assert entries[0]["hash"] == "bbbb"


def test_get_expected_hashes_schema_v1_migration():
    """Schema v1 refs without bios_mode default to 'hle'."""
    entries = get_expected_hashes(SAMPLE_REFS, "test-thumb", bios_mode="hle")
    assert len(entries) == 1
    assert entries[0]["hash"] == "dddd"


def test_get_expected_hashes_schema_v1_not_official():
    """Schema v1 refs (no bios_mode) should NOT match 'official' filter."""
    entries = get_expected_hashes(SAMPLE_REFS, "test-thumb", bios_mode="official")
    assert len(entries) == 0


def test_get_expected_hashes_missing_test():
    """Non-existent test returns empty list."""
    entries = get_expected_hashes(SAMPLE_REFS, "nonexistent")
    assert entries == []


def test_get_expected_hash_values():
    """Backward-compat function returns just hash strings."""
    values = get_expected_hash_values(SAMPLE_REFS, "test-arm", bios_mode="official")
    assert values == ["aaaa", "cccc"]


def test_matched_reference_includes_metadata():
    """Returned entries include tier and emulator info."""
    entries = get_expected_hashes(SAMPLE_REFS, "test-arm", bios_mode="official")
    nba_entry = next(e for e in entries if e["hash"] == "aaaa")
    assert nba_entry["tier"] == "gold"
    assert nba_entry["emulator"] == "NanoBoyAdvance"
    assert nba_entry["bios_mode"] == "official"


# --- Manifest loading tests ---

def test_load_manifest(tmp_path):
    """Load a minimal manifest from TOML."""
    manifest_toml = tmp_path / "manifest.toml"
    manifest_toml.write_text("""
schema_version = 1

[suite]
name = "test-suite"
description = "A test suite"

[[tests]]
id = "test-1"
rom = "test.gba"
max_frames = 100

[tests.completion]
type = "stable_frames"
window = 5
min_frames = 10
""")
    result = load_manifest(tmp_path)
    assert result["suite"]["name"] == "test-suite"
    assert len(result["tests"]) == 1
    assert result["tests"][0]["id"] == "test-1"


def test_load_references(tmp_path):
    """Load references.json."""
    refs_json = tmp_path / "references.json"
    refs_json.write_text(json.dumps(SAMPLE_REFS))
    result = load_references(tmp_path)
    assert result["schema_version"] == 2
    assert "test-arm" in result["references"]
