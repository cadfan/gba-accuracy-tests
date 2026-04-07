#!/usr/bin/env python3
"""Interactive reference verification — bootstraps ground truth.

The whole multi-emulator suite is downstream of one fact: nothing is
"correct" until a human has looked at the actual pass-state framebuffer
and blessed the hash. Cross-runner consensus is observation, not truth.
This script is the bootstrap loop that turns observations into ground
truth, one (test, BIOS mode) pair at a time.

Workflow per test+mode:
    1. Pick a runner (default: cable_club)
    2. Run the test, capture raw .bin
    3. Render the .bin to a 24-bit BMP (cable_club's native screenshot
       format — see compare.py:bin_to_bmp)
    4. Open the BMP in the user's default image viewer
    5. Print what the test's "pass" state should look like (drawn from
       the manifest's hint field)
    6. Ask the user: PASS / FAIL / NEEDS_FRAMES / NEEDS_INPUT / SKIP
    7. PASS -> write the hash + BMP path into verified.json
       FAIL -> mark as known-fail (also written, but with status="fail")
       NEEDS_FRAMES -> re-run with 2x max_frames
       NEEDS_INPUT -> stop and let the user edit manifest.toml
       SKIP -> move on

Output: <suite>/verified.json with schema:
    {
      "schema_version": 1,
      "tests": {
        "<test_id>": {
          "<bios_mode>": {
            "hash": "<sha256>",
            "screenshot": "verified/<test_id>-<mode>.bmp",
            "status": "pass" | "fail",
            "verified_by": "<env USER>",
            "verified_at": "<iso8601>",
            "runner": "<runner name>",
            "frames": <int>,
            "notes": "<optional human note>"
          }
        }
      }
    }

Usage:
    python scripts/verify_refs.py --suite jsmolka --test jsmolka-arm --mode official
    python scripts/verify_refs.py --suite jsmolka                      # walk all tests
    python scripts/verify_refs.py --suite jsmolka --runner mgba        # use mgba as the verifier
    python scripts/verify_refs.py --resume                              # skip already-verified
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUITES_DIR = REPO_ROOT / "suites"

sys.path.insert(0, str(REPO_ROOT))
# Two visual formats per verified frame:
#   .bmp — canonical, byte-identical to cable_club's desktop screenshot
#          format. Used for image-comparison tooling that wants closest-to-
#          source bits and predictable byte layout.
#   .png — convenience copy. Browsers, image viewers, Read-the-image-inline
#          flows, dashboard previews. Lossless from BGR555, no quantization,
#          but encoded so it's universally consumable.
from compare import bin_to_bmp, bin_to_png, hash_bgr555  # noqa: E402
from runners import get_runner  # noqa: E402

# Per-suite "what does pass look like" descriptions. These are bootstrap
# hints to help a human (especially one with aphantasia who can't visualize
# from a text description alone) decide whether the captured frame is in
# the test's pass state. Add to this dict as new suites are bootstrapped.
PASS_HINTS = {
    "jsmolka": {
        "default": (
            "jsmolka tests display a SOLID GREEN screen when all sub-tests pass. "
            "On failure, the screen shows 'Failed test NNN' on a red background. "
            "If you see green with no red text, that's a pass. If you see red text, "
            "that's a specific test failure (the number tells you which sub-test "
            "in the ROM source)."
        ),
        "jsmolka-bios": (
            "jsmolka-bios prints text results for each BIOS SWI tested. Pass = "
            "every line shows 'OK', no 'FAIL' lines visible. The screen will be "
            "mostly text on a dark background, not solid green."
        ),
        "jsmolka-ppu-hello": (
            "Should display the text 'Hello World' rendered as a tile pattern. "
            "Any visible 'Hello World' = pass."
        ),
        "jsmolka-ppu-shades": (
            "Should display a smooth horizontal gradient of color shades. "
            "Visible gradient with no obvious banding = pass."
        ),
        "jsmolka-ppu-stripes": (
            "Should display vertical stripes alternating between two colors. "
            "Clean stripes with no glitching = pass."
        ),
    },
    "armwrestler": {
        "default": (
            "ARMWrestler displays a list of test categories with results. "
            "Each line ends in either 'OK' or 'ER'. Pass = every visible line "
            "ends in 'OK'. The exact category depends on which sub-test you ran "
            "(arm-alu, arm-ldr-str, etc.) — the menu item is shown at the top."
        ),
    },
    "fuzzarm": {
        "default": (
            "FuzzARM runs 10,000 random instruction tests then displays a final "
            "summary screen with 'End of testing' and pass/fail counts. Pass = "
            "the counts show all tests passed (e.g., 10000/10000). If still on "
            "an in-progress screen, the test needs more frames."
        ),
    },
    "mgba-suite": {
        "default": (
            "mgba-suite shows a results page after each sub-suite runs. "
            "The format is 'category: passes/total'. Pass = all sub-categories "
            "show full ratios (e.g., '100/100'). If you see a menu instead of "
            "results, the input schedule didn't navigate into the right sub-suite."
        ),
    },
    "ags-aging": {
        "default": (
            "AGS Aging Cartridge displays a multi-section results page covering "
            "Memory, LCD, Timer, DMA, Key Input, and Interrupt sections. Pass = "
            "all sections show 'PASS' or '-OK-' indicators. Some sections (COM) "
            "are expected to N/A on a single emulator instance."
        ),
    },
}


def pass_hint(suite: str, test_id: str) -> str:
    suite_hints = PASS_HINTS.get(suite, {})
    return suite_hints.get(test_id) or suite_hints.get("default", "(no hint registered for this suite)")


def load_verified(suite_dir: Path) -> dict:
    path = suite_dir / "verified.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"schema_version": 1, "tests": {}}


def save_verified(suite_dir: Path, verified: dict) -> None:
    path = suite_dir / "verified.json"
    with open(path, "w") as f:
        json.dump(verified, f, indent=2)


def open_image(path: Path) -> None:
    """Open a BMP in the user's default viewer. Cross-platform best-effort."""
    abs_path = str(path.resolve())
    try:
        if os.name == "nt":
            os.startfile(abs_path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", abs_path], check=False)
        else:
            subprocess.run(["xdg-open", abs_path], check=False)
    except Exception as e:
        print(f"  [could not auto-open viewer: {e}]")
        print(f"  Open manually: {abs_path}")


def run_one(runner_name: str, suite: str, test: dict, bios_mode: str, frames_override: int | None = None) -> tuple[bytes, int] | None:
    """Run a single test through the chosen runner. Returns (raw_bytes, frames) or None on failure."""
    runner = get_runner(runner_name)
    if runner is None or not runner.is_available():
        print(f"  ERROR: runner '{runner_name}' is not available")
        return None
    suite_name = test.get("_suite_name", suite)
    rom_rel = test["rom"]
    rom_path = REPO_ROOT / "roms" / suite_name / rom_rel
    if not rom_path.exists():
        print(f"  ERROR: ROM not found at {rom_path}")
        return None
    frames = frames_override if frames_override is not None else int(test.get("max_frames", 600))
    inputs = test.get("input") or None
    completion = test.get("completion") or None

    test_id = test["id"]
    output_dir = REPO_ROOT / "test-output" / "verify"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{test_id}-{bios_mode}.bin"

    # Apply the same KEY_HOLD + BIOS-boot-offset transforms as generate_refs.
    if inputs:
        from generate_refs import expand_input_script, OFFICIAL_BIOS_BOOT_OFFSET
        expanded = expand_input_script(inputs)
        if bios_mode == "official" and expanded:
            expanded = [{"frame": i["frame"] + OFFICIAL_BIOS_BOOT_OFFSET, "keys": i["keys"]} for i in expanded]
            frames += OFFICIAL_BIOS_BOOT_OFFSET
        inputs = expanded

    print(f"  running {runner_name} on {test_id} ({bios_mode}, {frames} frames)…")
    ok = runner.run_test(
        rom_path,
        frames,
        output_path,
        inputs=inputs,
        completion=completion,
        bios_mode=bios_mode,
    )
    if not ok or not output_path.exists() or output_path.stat().st_size != 76800:
        print("  ERROR: runner did not produce a valid framebuffer")
        return None
    return output_path.read_bytes(), frames


def verify_one(suite: str, test: dict, bios_mode: str, runner_name: str, verified: dict) -> str:
    """Verify one (test, mode) pair interactively. Returns the next-action string:
    'verified', 'failed', 'skipped', 'aborted'."""
    test_id = test["id"]
    print()
    print("=" * 78)
    print(f"  TEST   : {test_id}")
    print(f"  MODE   : {bios_mode}")
    print(f"  RUNNER : {runner_name}")
    print(f"  HINT   : {pass_hint(suite, test_id)}")
    print("=" * 78)

    frames_override: int | None = None
    while True:
        result = run_one(runner_name, suite, test, bios_mode, frames_override=frames_override)
        if result is None:
            return "skipped"
        raw, frames = result
        h = hash_bgr555(raw)
        verify_dir = SUITES_DIR / suite / "verified"
        verify_dir.mkdir(parents=True, exist_ok=True)
        bmp_path = verify_dir / f"{test_id}-{bios_mode}.bmp"
        png_path = verify_dir / f"{test_id}-{bios_mode}.png"
        bin_to_bmp(raw, bmp_path)
        bin_to_png(raw, png_path)
        print(f"  hash : {h}")
        print(f"  bmp  : {bmp_path}")
        print(f"  png  : {png_path}")
        open_image(png_path)  # PNG opens reliably in any default viewer

        print()
        print("  Look at the image and tell me what you see.")
        print("    1) PASS   — the test is in its pass state, lock this hash as ground truth")
        print("    2) FAIL   — the test is showing a failure screen (record as known-fail)")
        print("    3) FRAMES — the test isn't done yet, re-run with 2x more frames")
        print("    4) INPUT  — the navigation didn't reach the test, I need to edit manifest.toml")
        print("    5) SKIP   — leave this one for later")
        print("    6) ABORT  — stop verifying entirely")
        choice = input("  > ").strip()

        if choice in ("1", "p", "P", "pass", "PASS"):
            entry = {
                "hash": h,
                "screenshot": str(bmp_path.relative_to(SUITES_DIR / suite)),
                "status": "pass",
                "verified_by": getpass.getuser(),
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "runner": runner_name,
                "frames": frames,
                "notes": input("  notes (optional, press enter to skip)> ").strip() or None,
            }
            verified["tests"].setdefault(test_id, {})[bios_mode] = entry
            return "verified"

        if choice in ("2", "f", "F", "fail", "FAIL"):
            entry = {
                "hash": h,
                "screenshot": str(bmp_path.relative_to(SUITES_DIR / suite)),
                "status": "fail",
                "verified_by": getpass.getuser(),
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "runner": runner_name,
                "frames": frames,
                "notes": input("  what's failing? (e.g. 'Failed test 235')> ").strip() or None,
            }
            verified["tests"].setdefault(test_id, {})[bios_mode] = entry
            return "failed"

        if choice in ("3", "frames", "FRAMES"):
            frames_override = (frames_override or frames) * 2
            print(f"  re-running with {frames_override} frames…")
            continue

        if choice in ("4", "input", "INPUT"):
            print("  Edit suites/<suite>/manifest.toml's [[tests.input]] schedule for this test, then come back and re-run verify_refs.py with the same args.")
            return "skipped"

        if choice in ("5", "s", "S", "skip", "SKIP"):
            return "skipped"

        if choice in ("6", "a", "A", "abort", "ABORT"):
            return "aborted"

        print("  unrecognized — pick 1-6")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive reference verification")
    parser.add_argument("--suite", "-s", required=True, help="Suite name")
    parser.add_argument("--test", "-t", help="Verify only this test_id")
    parser.add_argument("--mode", "-m", choices=["official", "hle", "cleanroom", "all"], default="all",
                        help="Verify only this BIOS mode (default: all 3)")
    parser.add_argument("--runner", "-r", default="cable_club", help="Runner to capture with")
    parser.add_argument("--resume", action="store_true",
                        help="Skip (test, mode) pairs that are already verified")
    args = parser.parse_args(argv)

    suite_dir = SUITES_DIR / args.suite
    if not (suite_dir / "manifest.toml").exists():
        print(f"no manifest at {suite_dir}/manifest.toml")
        return 2

    verified = load_verified(suite_dir)

    # Load the manifest as raw TOML so we get all fields including hints, inputs, completion.
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore
    with open(suite_dir / "manifest.toml", "rb") as f:
        manifest = tomllib.load(f)
    suite_name = manifest.get("suite", {}).get("name", args.suite)
    tests = manifest.get("tests", [])
    for t in tests:
        t["_suite_name"] = suite_name

    if args.test:
        tests = [t for t in tests if t["id"] == args.test]
    if not tests:
        print(f"no tests matched")
        return 2

    modes = ["official", "hle", "cleanroom"] if args.mode == "all" else [args.mode]

    print(f"verifying {len(tests)} test(s) × {len(modes)} BIOS mode(s) = {len(tests) * len(modes)} pairs")
    print(f"runner   : {args.runner}")
    print(f"output   : {suite_dir}/verified.json")

    aborted = False
    for t in tests:
        if aborted:
            break
        for mode in modes:
            existing = verified.get("tests", {}).get(t["id"], {}).get(mode)
            if args.resume and existing and existing.get("status") in ("pass", "fail"):
                print(f"  [resume] skip {t['id']} ({mode}) — already {existing['status']}")
                continue
            result = verify_one(args.suite, t, mode, args.runner, verified)
            save_verified(suite_dir, verified)
            if result == "aborted":
                aborted = True
                break

    print()
    print(f"verified.json written to {suite_dir / 'verified.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
