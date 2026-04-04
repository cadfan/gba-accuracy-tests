#!/usr/bin/env python3
"""GBA accuracy test comparison tool.

Runs GBA test ROMs via emulator runners, compares framebuffer hashes against
reference outputs, and reports pass/fail with diff images.

Usage:
    python compare.py run --runner mgba --suite jsmolka
    python compare.py run --command "my-emu --headless {rom} --frames {frames} --screenshot {output}" --suite jsmolka
    python compare.py download --suite jsmolka
    python compare.py verify --screenshots ./my-output/ --suite jsmolka
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent
SUITES_DIR = REPO_ROOT / "suites"
ROMS_DIR = REPO_ROOT / "roms"
OUTPUT_DIR = REPO_ROOT / "test-output"

GBA_WIDTH = 240
GBA_HEIGHT = 160
FB_PIXEL_COUNT = GBA_WIDTH * GBA_HEIGHT
FB_BYTE_COUNT = FB_PIXEL_COUNT * 2  # u16 per pixel


# --- BGR555 conversion ---

def png_to_bgr555(png_path: Path) -> bytes:
    """Convert a 240x160 PNG to raw BGR555 little-endian bytes."""
    from PIL import Image

    img = Image.open(png_path).convert("RGB")
    if img.size != (GBA_WIDTH, GBA_HEIGHT):
        raise ValueError(f"Image is {img.size}, expected ({GBA_WIDTH}, {GBA_HEIGHT})")

    pixels = img.load()
    buf = bytearray(FB_BYTE_COUNT)
    for y in range(GBA_HEIGHT):
        for x in range(GBA_WIDTH):
            r8, g8, b8 = pixels[x, y]
            r5 = (r8 >> 3) & 0x1F
            g5 = (g8 >> 3) & 0x1F
            b5 = (b8 >> 3) & 0x1F
            u16 = r5 | (g5 << 5) | (b5 << 10)
            offset = (y * GBA_WIDTH + x) * 2
            struct.pack_into("<H", buf, offset, u16)
    return bytes(buf)


def load_screenshot(path: Path) -> bytes:
    """Load a screenshot as raw BGR555 LE bytes."""
    if path.suffix == ".bin":
        data = path.read_bytes()
        if len(data) != FB_BYTE_COUNT:
            raise ValueError(f"Raw file is {len(data)} bytes, expected {FB_BYTE_COUNT}")
        return data
    return png_to_bgr555(path)


def hash_bgr555(raw: bytes) -> str:
    """SHA256 hash of raw BGR555 LE framebuffer bytes."""
    return hashlib.sha256(raw).hexdigest()


# --- Diff image generation ---

def generate_triptych(expected_raw: bytes, actual_raw: bytes, output_path: Path) -> None:
    """Generate Expected | Actual | Diff triptych (720x160 PNG)."""
    from PIL import Image

    def raw_to_image(raw: bytes) -> Image.Image:
        img = Image.new("RGB", (GBA_WIDTH, GBA_HEIGHT))
        pixels = img.load()
        for y in range(GBA_HEIGHT):
            for x in range(GBA_WIDTH):
                offset = (y * GBA_WIDTH + x) * 2
                u16 = struct.unpack_from("<H", raw, offset)[0]
                r = ((u16 & 0x1F) << 3)
                g = (((u16 >> 5) & 0x1F) << 3)
                b = (((u16 >> 10) & 0x1F) << 3)
                pixels[x, y] = (r, g, b)
        return img

    expected_img = raw_to_image(expected_raw)
    actual_img = raw_to_image(actual_raw)

    diff_img = Image.new("RGB", (GBA_WIDTH, GBA_HEIGHT))
    diff_pixels = diff_img.load()
    exp_pixels = expected_img.load()
    act_pixels = actual_img.load()
    for y in range(GBA_HEIGHT):
        for x in range(GBA_WIDTH):
            if exp_pixels[x, y] != act_pixels[x, y]:
                diff_pixels[x, y] = (255, 0, 255)  # magenta
            else:
                r, g, b = act_pixels[x, y]
                diff_pixels[x, y] = (r // 4, g // 4, b // 4)

    triptych = Image.new("RGB", (GBA_WIDTH * 3, GBA_HEIGHT))
    triptych.paste(expected_img, (0, 0))
    triptych.paste(actual_img, (GBA_WIDTH, 0))
    triptych.paste(diff_img, (GBA_WIDTH * 2, 0))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    triptych.save(output_path)


# --- Manifest and reference loading ---

def load_manifest(suite_dir: Path) -> dict:
    """Load a suite manifest from TOML."""
    manifest_path = suite_dir / "manifest.toml"
    with open(manifest_path, "rb") as f:
        return tomllib.load(f)


def load_references(suite_dir: Path) -> dict:
    """Load references.json for a suite."""
    refs_path = suite_dir / "references.json"
    with open(refs_path) as f:
        return json.load(f)


def get_expected_hashes(refs: dict, test_id: str) -> list[str]:
    """Get all valid reference hashes for a test (any tier)."""
    entries = refs.get("references", {}).get(test_id, [])
    return [e["hash"] for e in entries if "hash" in e]


# --- Test execution ---

class TestStatus:
    PASS = "PASS"
    FAIL = "FAIL"
    CRASH = "CRASH"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    SKIP = "SKIP"


def run_with_runner(runner, rom_path: Path, frames: int, output_path: Path) -> str:
    """Run a test via a runner adapter. Returns status string."""
    try:
        success = runner.run_test(rom_path, frames, output_path)
        if not success:
            if output_path.exists():
                return TestStatus.ERROR
            return TestStatus.CRASH
        return TestStatus.PASS  # runner succeeded, hash comparison happens later
    except Exception:
        return TestStatus.ERROR


def run_with_command(cmd_template: list[str], rom_path: Path, frames: int, output_path: Path) -> str:
    """Run a test via CLI command template. Returns status string."""
    cmd = []
    for arg in cmd_template:
        cmd.append(
            arg.replace("{rom}", str(rom_path))
               .replace("{frames}", str(frames))
               .replace("{output}", str(output_path))
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(cmd, timeout=60, capture_output=True)
        if result.returncode != 0:
            return TestStatus.CRASH
        if not output_path.exists() or output_path.stat().st_size == 0:
            return TestStatus.ERROR
        return TestStatus.PASS
    except subprocess.TimeoutExpired:
        return TestStatus.TIMEOUT
    except OSError:
        return TestStatus.ERROR


# --- Main commands ---

def cmd_run(args: argparse.Namespace) -> int:
    """Run tests and compare against references."""
    from runners import get_runner

    runner = None
    cmd_template = None

    if args.command:
        # Parse command template into arg list (no shlex — explicit split)
        cmd_template = args.command
    elif args.runner:
        runner = get_runner(args.runner)
        if runner is None:
            print(f"Runner '{args.runner}' not found. Available: {', '.join(__import__('runners').list_runners())}")
            return 2
        if not runner.is_available():
            print(f"Runner '{args.runner}' is not available (emulator not installed?)")
            return 2
    else:
        print("Specify --runner or --command")
        return 2

    suites = _get_suites(args.suite)
    if not suites:
        return 2

    results = []
    total_pass, total_fail, total_other = 0, 0, 0

    print(f"\ngba-accuracy-tests v0.1.0\n")

    for suite_dir in suites:
        manifest = load_manifest(suite_dir)
        refs = load_references(suite_dir)
        tests = manifest.get("tests", [])
        suite_name = manifest.get("suite", {}).get("name", suite_dir.name)

        for i, test in enumerate(tests, 1):
            test_id = test["id"]
            rom_rel = test["rom"]
            rom_path = ROMS_DIR / suite_name / rom_rel
            max_frames = test.get("max_frames", 600)
            hint = test.get("hint", "")

            if not rom_path.exists():
                print(f"  [{i}/{len(tests)}] {test_id:<30} SKIP   ROM not found: {rom_path}")
                print(f"           Run: python scripts/download_roms.py --suite {suite_name}")
                total_other += 1
                results.append({"test_id": test_id, "status": TestStatus.SKIP})
                continue

            output_path = OUTPUT_DIR / f"{test_id}.png"
            t0 = time.monotonic()

            if runner:
                status = run_with_runner(runner, rom_path, max_frames, output_path)
            else:
                status = run_with_command(cmd_template, rom_path, max_frames, output_path)

            elapsed = time.monotonic() - t0

            if status in (TestStatus.CRASH, TestStatus.TIMEOUT, TestStatus.ERROR):
                print(f"  [{i}/{len(tests)}] {test_id:<30} {status}  ({elapsed:.1f}s)")
                total_other += 1
                results.append({"test_id": test_id, "status": status, "time_s": round(elapsed, 1)})
                continue

            # Compare hash
            try:
                actual_raw = load_screenshot(output_path)
                actual_hash = hash_bgr555(actual_raw)
            except (ValueError, FileNotFoundError, OSError) as e:
                print(f"  [{i}/{len(tests)}] {test_id:<30} ERROR  {e}")
                total_other += 1
                results.append({"test_id": test_id, "status": TestStatus.ERROR})
                continue

            expected_hashes = get_expected_hashes(refs, test_id)

            if not expected_hashes:
                print(f"  [{i}/{len(tests)}] {test_id:<30} SKIP   No reference hashes")
                total_other += 1
                results.append({"test_id": test_id, "status": TestStatus.SKIP, "actual_hash": actual_hash})
                continue

            if actual_hash in expected_hashes:
                print(f"  [{i}/{len(tests)}] {test_id:<30} PASS   ({elapsed:.1f}s)")
                total_pass += 1
                results.append({"test_id": test_id, "status": TestStatus.PASS, "time_s": round(elapsed, 1)})
            else:
                diff_path = OUTPUT_DIR / f"{test_id}.diff.png"
                # Try to generate diff image
                try:
                    # Use first reference hash's raw data for diff (need reference screenshots)
                    # For now just report the mismatch
                    pass
                except Exception:
                    pass
                print(f"  [{i}/{len(tests)}] {test_id:<30} FAIL   hash mismatch ({elapsed:.1f}s)")
                if hint:
                    print(f"           Hint: {hint}")
                total_fail += 1
                results.append({
                    "test_id": test_id,
                    "status": TestStatus.FAIL,
                    "actual_hash": actual_hash,
                    "expected_hashes": expected_hashes,
                    "time_s": round(elapsed, 1),
                })

    total = total_pass + total_fail + total_other
    print(f"\n{'='*50}")
    print(f"  TOTAL   {total_pass}/{total} passing ({100*total_pass/max(total,1):.1f}%)")
    if total_fail:
        print(f"  FAIL    {total_fail}")
    if total_other:
        print(f"  OTHER   {total_other} (skip/crash/timeout/error)")
    print(f"{'='*50}")

    # Write results JSON
    results_dir = REPO_ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    runner_name = args.runner or "command"
    suite_label = args.suite or "all"
    results_path = results_dir / f"{runner_name}-{suite_label}-{ts}.json"
    with open(results_path, "w") as f:
        json.dump({
            "schema_version": 1,
            "runner": runner_name,
            "suite": suite_label,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {"pass": total_pass, "fail": total_fail, "other": total_other},
            "results": results,
        }, f, indent=2)
    print(f"\nResults: {results_path}")

    return 1 if total_fail > 0 else 0


def cmd_download(args: argparse.Namespace) -> int:
    """Download test ROMs."""
    from scripts.download_roms import main as dl_main
    dl_args = []
    if args.suite:
        dl_args.extend(["--suite", args.suite])
    if args.force:
        dl_args.append("--force")
    return dl_main(dl_args)


def cmd_verify(args: argparse.Namespace) -> int:
    """Compare pre-captured screenshots against references."""
    screenshots_dir = Path(args.screenshots)
    if not screenshots_dir.exists():
        print(f"Screenshots directory not found: {screenshots_dir}")
        return 2

    suites = _get_suites(args.suite)
    if not suites:
        return 2

    total_pass, total_fail = 0, 0

    for suite_dir in suites:
        refs = load_references(suite_dir)
        for test_id, ref_entries in refs.get("references", {}).items():
            screenshot = screenshots_dir / f"{test_id}.png"
            if not screenshot.exists():
                screenshot = screenshots_dir / f"{test_id}.bin"
            if not screenshot.exists():
                print(f"  {test_id:<30} SKIP   no screenshot")
                continue

            try:
                actual_raw = load_screenshot(screenshot)
                actual_hash = hash_bgr555(actual_raw)
            except (ValueError, OSError) as e:
                print(f"  {test_id:<30} ERROR  {e}")
                continue

            expected = [e["hash"] for e in ref_entries if "hash" in e]
            if actual_hash in expected:
                print(f"  {test_id:<30} PASS")
                total_pass += 1
            else:
                print(f"  {test_id:<30} FAIL   hash mismatch")
                total_fail += 1

    print(f"\n{total_pass} pass, {total_fail} fail")
    return 1 if total_fail > 0 else 0


def _get_suites(suite_name: str | None) -> list[Path]:
    """Get suite directories to process."""
    if suite_name:
        suite_dir = SUITES_DIR / suite_name
        if not suite_dir.exists():
            print(f"Suite not found: {suite_name}")
            print(f"Available: {', '.join(d.name for d in SUITES_DIR.iterdir() if d.is_dir())}")
            return []
        return [suite_dir]
    return sorted(d for d in SUITES_DIR.iterdir() if d.is_dir() and (d / "manifest.toml").exists())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="compare.py",
        description="GBA accuracy test comparison tool",
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    # run
    run_p = subparsers.add_parser("run", help="Run tests and compare against references")
    run_p.add_argument("--runner", "-r", help="Runner name (e.g., mgba, cable-club)")
    run_p.add_argument("--command", "-c", nargs=argparse.REMAINDER,
                       help="CLI command template with {rom}, {frames}, {output} placeholders")
    run_p.add_argument("--suite", "-s", help="Suite to run (default: all)")
    run_p.set_defaults(func=cmd_run)

    # download
    dl_p = subparsers.add_parser("download", help="Download test ROMs")
    dl_p.add_argument("--suite", "-s", help="Suite to download")
    dl_p.add_argument("--force", action="store_true", help="Re-download existing files")
    dl_p.set_defaults(func=cmd_download)

    # verify
    verify_p = subparsers.add_parser("verify", help="Compare pre-captured screenshots against references")
    verify_p.add_argument("--screenshots", required=True, help="Directory of screenshot files")
    verify_p.add_argument("--suite", "-s", help="Suite to verify")
    verify_p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
