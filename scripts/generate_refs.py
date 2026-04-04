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

    suite_dir = SUITES_DIR / args.suite
    manifest = load_manifest(suite_dir)
    tests = manifest.get("tests", [])
    suite_name = manifest.get("suite", {}).get("name", args.suite)

    # Load existing references
    refs_path = suite_dir / "references.json"
    if refs_path.exists():
        with open(refs_path) as f:
            refs = json.load(f)
    else:
        refs = {"schema_version": 1, "references": {}}

    for test in tests:
        test_id = test["id"]
        if args.test and test_id != args.test:
            continue

        rom_path = ROMS_DIR / suite_name / test["rom"]
        if not rom_path.exists():
            print(f"  [{test_id}] SKIP — ROM not found: {rom_path}")
            continue

        max_frames = test.get("max_frames", 600)
        output_path = OUTPUT_DIR / f"ref-{test_id}.png"

        print(f"  [{test_id}] Running {max_frames} frames...")
        success = runner.run_test(rom_path, max_frames, output_path)
        if not success:
            print(f"  [{test_id}] FAIL — runner did not produce output")
            continue

        try:
            raw = load_screenshot(output_path)
            ref_hash = hash_bgr555(raw)
        except (ValueError, OSError) as e:
            print(f"  [{test_id}] ERROR — {e}")
            continue

        entry = {
            "hash": ref_hash,
            "tier": "secondary",
            "provenance": {
                "emulator": runner.name,
                "version": None,
                "commit": None,
                "bios": None,
                "rom_sha256": test.get("rom_sha256"),
                "frame_count": max_frames,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "captured_by": "generate_refs.py",
            },
        }

        if test_id not in refs["references"]:
            refs["references"][test_id] = []

        # Replace existing entry from same emulator, or append
        existing = refs["references"][test_id]
        replaced = False
        for i, e in enumerate(existing):
            if e.get("provenance", {}).get("emulator") == runner.name:
                existing[i] = entry
                replaced = True
                break
        if not replaced:
            existing.append(entry)

        print(f"  [{test_id}] {ref_hash[:16]}...")

    with open(refs_path, "w") as f:
        json.dump(refs, f, indent=2)
    print(f"\nReferences written to: {refs_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate reference hashes")
    parser.add_argument("--runner", "-r", required=True, help="Runner name")
    parser.add_argument("--suite", "-s", required=True, help="Suite name")
    parser.add_argument("--test", "-t", help="Specific test ID")
    args = parser.parse_args(argv)
    return generate_refs(args)


if __name__ == "__main__":
    sys.exit(main())
