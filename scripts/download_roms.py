#!/usr/bin/env python3
"""Download pre-built GBA test ROM binaries.

Pins each suite to a specific commit SHA for reproducibility.
Verifies SHA256 checksums after download. Uses atomic rename to
prevent partial/corrupt files.

Usage:
    python download_roms.py                  # Download all suites
    python download_roms.py --suite jsmolka  # Download one suite
    python download_roms.py --force          # Re-download existing files
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROMS_DIR = REPO_ROOT / "roms"

# ROM sources: suite name -> (repo, commit, [(file, sha256)])
ROM_MANIFEST: dict[str, tuple[str, str, list[tuple[str, str]]]] = {
    "jsmolka": (
        "jsmolka/gba-tests",
        "a7113b67e63f83a9b321696ddd7042ccfad6c881",
        [
            ("arm/arm.gba", "77ee88662552bdc885c1080c0172ff119d54db791bd73b21808cf1ff1fe5b40e"),
            ("thumb/thumb.gba", "b5cb2291df4ab314b31c598acd9bff2ccfa0b38efff29daadfe97422ce369b67"),
            ("bios/bios.gba", "9d7b369fa1aa661ff03692b3d79c6f644b623d72983d0fc890e6d87a0409a3c9"),
            ("memory/memory.gba", "21024fb6aae6343f5f0466dd54e3149de1fbeb23f78e7d85a015c983684d2f87"),
            ("nes/nes.gba", "d990df112763087d0415b3785c1b4d31c0237794a704d0446fc5f5e474a44f98"),
            ("unsafe/unsafe.gba", "bb727d59fa81915a5f5c609f4befb64872d3a3d830bc6ae0149e26410e648f85"),
        ],
    ),
    "armwrestler": (
        "destoer/armwrestler-gba-fixed",
        "802e55ad61b421f4bbbc6f74f96aa4e5df4d630f",
        [
            ("armwrestler-gba-fixed.gba", "9f08d807c03ef296d38ef73e9b827a3d8c77cead9ced44b07d64c10f5f7d0746"),
        ],
    ),
    "fuzzarm": (
        "DenSinH/FuzzARM",
        "a675329cd57da48e3e406216ba2d79dd7e09ee20",
        [
            ("FuzzARM.gba", ""),  # SHA256 not yet verified
        ],
    ),
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path, expected_sha256: str, force: bool = False) -> bool:
    if dest.exists() and not force:
        if expected_sha256:
            actual = sha256_file(dest)
            if actual == expected_sha256:
                print(f"  [skip] {dest.name} (exists, checksum OK)")
                return True
            print(f"  [WARN] {dest.name} checksum mismatch, re-downloading")
        else:
            print(f"  [skip] {dest.name} (exists)")
            return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")

    for attempt in range(2):
        try:
            print(f"  [fetch] {dest.name}" + (" (retry)" if attempt > 0 else ""))
            urllib.request.urlretrieve(url, tmp)
        except (urllib.error.URLError, OSError) as e:
            print(f"  [FAIL] {e}")
            tmp.unlink(missing_ok=True)
            if attempt == 0:
                continue
            return False

        if expected_sha256:
            actual = sha256_file(tmp)
            if actual != expected_sha256:
                print(f"  [FAIL] SHA256 mismatch: expected {expected_sha256[:16]}..., got {actual[:16]}...")
                tmp.unlink(missing_ok=True)
                if attempt == 0:
                    continue
                return False

        tmp.rename(dest)
        return True

    return False


def download_suite(name: str, force: bool = False) -> tuple[int, int]:
    if name not in ROM_MANIFEST:
        print(f"Unknown suite: {name}")
        return 0, 0

    repo, commit, files = ROM_MANIFEST[name]
    suite_dir = ROMS_DIR / name
    ok, fail = 0, 0

    for filename, expected_sha in files:
        url = f"https://raw.githubusercontent.com/{repo}/{commit}/{filename}"
        dest = suite_dir / filename
        if download_file(url, dest, expected_sha, force):
            ok += 1
        else:
            fail += 1

    return ok, fail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download GBA test ROMs")
    parser.add_argument("--suite", "-s", help="Download specific suite only")
    parser.add_argument("--force", action="store_true", help="Re-download existing files")
    args = parser.parse_args(argv)

    suites = [args.suite] if args.suite else list(ROM_MANIFEST.keys())
    total_ok, total_fail = 0, 0

    print("Downloading GBA test ROMs...\n")
    for i, name in enumerate(suites, 1):
        print(f"[{i}/{len(suites)}] {name}")
        ok, fail = download_suite(name, args.force)
        total_ok += ok
        total_fail += fail
        print()

    print(f"Done. {total_ok} downloaded, {total_fail} failed.")
    print(f"ROMs in: {ROMS_DIR}")
    return 1 if total_fail > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
