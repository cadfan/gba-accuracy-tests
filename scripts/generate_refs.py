#!/usr/bin/env python3
"""Generate reference hashes from an emulator runner.

Runs test ROMs, captures framebuffers, converts to BGR555 LE,
hashes with SHA256, and writes provenance-rich references.json.

Usage:
    python generate_refs.py --runner mgba --suite jsmolka
    python generate_refs.py --runner mgba --test jsmolka-arm
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compare import load_manifest, load_screenshot, hash_bgr555, SUITES_DIR, ROMS_DIR, OUTPUT_DIR
from runners import get_runner


def generate_refs(args: argparse.Namespace) -> int:
    runner = get_runner(args.runner)
    if runner is None or not runner.is_available():
        print(f"Runner '{args.runner}' not available")
        return 2

    bios_mode = args.bios_mode
    tier = args.tier

    suite_dir = SUITES_DIR / args.suite
    manifest = load_manifest(suite_dir)
    tests = manifest.get("tests", [])
    suite_name = manifest.get("suite", {}).get("name", args.suite)

    # Load existing references (migrate to schema v2 if needed)
    refs_path = suite_dir / "references.json"
    if refs_path.exists():
        with open(refs_path) as f:
            refs = json.load(f)
    else:
        refs = {"schema_version": 2, "references": {}}

    if refs.get("schema_version", 1) < 2:
        refs["schema_version"] = 2

    # Directory for storing raw framebuffer .bin files
    refs_bin_dir = suite_dir / "refs"
    refs_bin_dir.mkdir(exist_ok=True)

    for test in tests:
        test_id = test["id"]
        if args.test and test_id != args.test:
            continue

        rom_path = ROMS_DIR / suite_name / test["rom"]
        if not rom_path.exists():
            print(f"  [{test_id}] SKIP \u2014 ROM not found: {rom_path}")
            continue

        max_frames = test.get("max_frames", 600)
        output_path = OUTPUT_DIR / f"ref-{test_id}.png"

        print(f"  [{test_id}] Running {max_frames} frames (bios={bios_mode})...")
        success = runner.run_test(rom_path, max_frames, output_path)
        if not success:
            print(f"  [{test_id}] FAIL \u2014 runner did not produce output")
            continue

        try:
            raw = load_screenshot(output_path)
            ref_hash = hash_bgr555(raw)
        except (ValueError, OSError) as e:
            print(f"  [{test_id}] ERROR \u2014 {e}")
            continue

        # Store raw framebuffer .bin for diff triptych generation
        emu_slug = runner.name.lower().replace(" ", "-")
        bin_path = refs_bin_dir / f"{emu_slug}-{bios_mode}-{test_id}.bin"
        bin_path.write_bytes(raw)

        entry = {
            "hash": ref_hash,
            "tier": tier,
            "bios_mode": bios_mode,
            "provenance": {
                "emulator": runner.name,
                "version": None,
                "commit": None,
                "bios_mode": bios_mode,
                "bios_sha256": None,
                "rom_sha256": test.get("rom_sha256"),
                "frame_count": max_frames,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "captured_by": "generate_refs.py",
            },
        }

        if test_id not in refs["references"]:
            refs["references"][test_id] = []

        # Replace existing entry from same emulator + bios_mode, or append
        existing = refs["references"][test_id]
        replaced = False
        for i, e in enumerate(existing):
            prov = e.get("provenance", {})
            same_emu = prov.get("emulator") == runner.name
            same_bios = e.get("bios_mode", prov.get("bios_mode", "hle")) == bios_mode
            if same_emu and same_bios:
                existing[i] = entry
                replaced = True
                break
        if not replaced:
            existing.append(entry)

        print(f"  [{test_id}] {ref_hash[:16]}... ({tier}/{bios_mode})")

    with open(refs_path, "w") as f:
        json.dump(refs, f, indent=2)
    print(f"\nReferences written to: {refs_path}")
    print(f"Raw framebuffers in: {refs_bin_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate reference hashes")
    parser.add_argument("--runner", "-r", required=True, help="Runner name")
    parser.add_argument("--suite", "-s", required=True, help="Suite name")
    parser.add_argument("--test", "-t", help="Specific test ID")
    parser.add_argument("--bios-mode", "-b", default="hle",
                        choices=["official", "hle", "skip", "cleanroom"],
                        help="BIOS mode used for this run (default: hle)")
    parser.add_argument("--tier", default="secondary",
                        choices=["gold", "secondary", "candidate"],
                        help="Reference tier (default: secondary)")
    args = parser.parse_args(argv)
    return generate_refs(args)


if __name__ == "__main__":
    sys.exit(main())
