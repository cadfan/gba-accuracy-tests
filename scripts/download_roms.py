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

# Two source kinds:
#   "github_raw": files come from a single pinned commit on a GitHub repo.
#       (repo, commit, [(file, sha256)])
#   "direct": files come from individual URLs (mirrors, archives, wiki).
#       [(filename_relative, url, sha256)]
ROM_MANIFEST: dict[str, dict] = {
    "jsmolka": {
        "kind": "github_raw",
        "repo": "jsmolka/gba-tests",
        "commit": "a7113b67e63f83a9b321696ddd7042ccfad6c881",
        "files": [
            ("arm/arm.gba", "77ee88662552bdc885c1080c0172ff119d54db791bd73b21808cf1ff1fe5b40e"),
            ("thumb/thumb.gba", "b5cb2291df4ab314b31c598acd9bff2ccfa0b38efff29daadfe97422ce369b67"),
            ("bios/bios.gba", "9d7b369fa1aa661ff03692b3d79c6f644b623d72983d0fc890e6d87a0409a3c9"),
            ("memory/memory.gba", "21024fb6aae6343f5f0466dd54e3149de1fbeb23f78e7d85a015c983684d2f87"),
            ("nes/nes.gba", "d990df112763087d0415b3785c1b4d31c0237794a704d0446fc5f5e474a44f98"),
            ("unsafe/unsafe.gba", "bb727d59fa81915a5f5c609f4befb64872d3a3d830bc6ae0149e26410e648f85"),
            ("save/none.gba", "edb34ba6590d070c8a50cf0f3566b1e3cc679377b978224ff1b872d27f2b1630"),
            ("save/sram.gba", "a37ad99c31e3f805eb05a00e498b65bd78e6f43a0a139cd695bea1f88229af2c"),
            ("save/flash64.gba", "7e2aa32e943aedde88bd750eadcdbf55152d3a1ec61385011b7f15cd85b07c02"),
            ("save/flash128.gba", "9ac50e51d3ce4209dbdf85e472e70c067d5827e9af1bb3e707f6bd9059d5f0c6"),
            # PPU mode-specific framebuffer tests (live in ppu/ subdir).
            ("ppu/hello.gba", ""),
            ("ppu/shades.gba", ""),
            ("ppu/stripes.gba", ""),
        ],
    },
    "armwrestler": {
        "kind": "github_raw",
        "repo": "destoer/armwrestler-gba-fixed",
        "commit": "802e55ad61b421f4bbbc6f74f96aa4e5df4d630f",
        "files": [
            ("armwrestler-gba-fixed.gba", "9f08d807c03ef296d38ef73e9b827a3d8c77cead9ced44b07d64c10f5f7d0746"),
        ],
    },
    "fuzzarm": {
        "kind": "github_raw",
        "repo": "DenSinH/FuzzARM",
        "commit": "a675329cd57da48e3e406216ba2d79dd7e09ee20",
        "files": [
            ("ARM_Any.gba",   "5db4e020a61a0760043cb66b7149fa1777501080dbfc1b956c9600d44a4500f5"),
            ("THUMB_Any.gba", "c89d9e0894d9ef5af5de6bf7819b32383acad535ec5ab8c7e5b4f6278dff34f6"),
            ("FuzzARM.gba",   "266e3d4f1dc231aadf9d296b13897cdc0de4c3cef73cf0c83806c0cef3422269"),
        ],
    },
    "mgba-suite": {
        # mgba-emu/suite has no pre-built release; the only sourceable
        # binary is the one Asphaltian/sgba bundles for their test fixtures.
        # If that mirror disappears we can build from source via devkitARM
        # — see Makefile in the upstream mgba-emu/suite repo.
        "kind": "direct",
        "files": [
            (
                "suite.gba",
                "https://raw.githubusercontent.com/Asphaltian/sgba/main/Assets/roms/suite.gba",
                "2748b498310e77a4ec7f0c89459fa9d61986284977fa801d18f0564c83b7ebb6",
            ),
        ],
    },
    "ags-aging": {
        # The AGS Aging Cartridge (factory hardware QA tool) is hosted on
        # The Cutting Room Floor wiki — multiple versions available. We
        # pull the v7.1 (World) build because it's the most complete.
        # The ROM is the cartridge contents, NOT the GBA BIOS — different
        # thing. See BIOS.md for the BIOS situation.
        "kind": "direct",
        "files": [
            (
                "ags-aging.gba",
                "https://tcrf.net/images/f/f4/AGS_Aging_Cartridge_%28World%29_%28v7.1%29.zip#unzip=AGS Aging Cartridge (World) (v7.1).gba",
                "6968bd01df531b4ca4b9777a87c1913fb6ff3783ef378d04476d531be9b6765d",
            ),
        ],
    },
}

# Cult-of-GBA replacement BIOS — separate from ROMs because it lives in
# runners/cores/, not roms/. Tracked here so download_roms.py can also
# (re-)bootstrap the BIOS in one shot via --bios.
CLEANROOM_BIOS = {
    "url": (
        "https://raw.githubusercontent.com/Cult-of-GBA/BIOS/"
        "a30e9a96df083628b650724b7d4d7112b4070b98/bios.bin"
    ),
    "dest": REPO_ROOT / "runners" / "cores" / "gba_bios_cleanroom.bin",
    "sha256": "61af6e8c2db6cf24aa6924e8133f6a50833158fca33ff08ea5e11e1a06e132f2",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _request(url: str, dest: Path) -> None:
    """urlretrieve with a User-Agent header (TCRF, Cult-of-GBA, and a few
    other hosts return 403 to the bare urllib UA)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (gba-accuracy-tests download_roms.py)"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)


def _extract_zip_member(archive: Path, member: str, dest: Path) -> None:
    import zipfile
    with zipfile.ZipFile(archive, "r") as z:
        with z.open(member) as src, open(dest, "wb") as out:
            while True:
                chunk = src.read(65536)
                if not chunk:
                    break
                out.write(chunk)


def download_file(url: str, dest: Path, expected_sha256: str, force: bool = False) -> bool:
    """Download a single file with optional zip extraction.

    URL fragment syntax extends to support archive extraction:
        https://example.com/archive.zip#unzip=path/inside.gba
    fetches the zip into a temp file, then extracts the named member to `dest`.
    """
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

    # Handle the #unzip=member fragment separately so the rest of the code
    # works on a single fetch destination.
    fetch_url = url
    extract_member: str | None = None
    if "#unzip=" in url:
        fetch_url, extract_member = url.split("#unzip=", 1)

    if extract_member is not None:
        archive_tmp = dest.with_suffix(".zip.tmp")
        try:
            print(f"  [fetch] {dest.name} (zip)")
            _request(fetch_url, archive_tmp)
            extracted_tmp = dest.with_suffix(dest.suffix + ".tmp")
            _extract_zip_member(archive_tmp, extract_member, extracted_tmp)
            tmp = extracted_tmp
        except (urllib.error.URLError, OSError, KeyError) as e:
            print(f"  [FAIL] {e}")
            archive_tmp.unlink(missing_ok=True)
            return False
        finally:
            archive_tmp.unlink(missing_ok=True)
    else:
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        for attempt in range(2):
            try:
                print(f"  [fetch] {dest.name}" + (" (retry)" if attempt > 0 else ""))
                _request(fetch_url, tmp)
                break
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
            return False

    tmp.replace(dest)
    return True


def download_suite(name: str, force: bool = False) -> tuple[int, int]:
    if name not in ROM_MANIFEST:
        print(f"Unknown suite: {name}")
        return 0, 0

    entry = ROM_MANIFEST[name]
    suite_dir = ROMS_DIR / name
    ok, fail = 0, 0

    if entry["kind"] == "github_raw":
        repo = entry["repo"]
        commit = entry["commit"]
        for filename, expected_sha in entry["files"]:
            url = f"https://raw.githubusercontent.com/{repo}/{commit}/{filename}"
            dest = suite_dir / filename
            if download_file(url, dest, expected_sha, force):
                ok += 1
            else:
                fail += 1
    elif entry["kind"] == "direct":
        for filename, url, expected_sha in entry["files"]:
            dest = suite_dir / filename
            if download_file(url, dest, expected_sha, force):
                ok += 1
            else:
                fail += 1
    else:
        print(f"  [FAIL] unknown source kind for {name}: {entry.get('kind')}")

    return ok, fail


def download_cleanroom_bios(force: bool = False) -> bool:
    print("[cleanroom BIOS] Cult-of-GBA replacement BIOS (MIT)")
    return download_file(
        CLEANROOM_BIOS["url"],
        CLEANROOM_BIOS["dest"],
        CLEANROOM_BIOS["sha256"],
        force=force,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download GBA test ROMs and the cleanroom BIOS")
    parser.add_argument("--suite", "-s", help="Download specific suite only")
    parser.add_argument("--force", action="store_true", help="Re-download existing files")
    parser.add_argument("--bios", action="store_true",
                        help="Also (re-)download the Cult-of-GBA cleanroom BIOS")
    parser.add_argument("--bios-only", action="store_true",
                        help="Only download the Cult-of-GBA cleanroom BIOS, not ROMs")
    args = parser.parse_args(argv)

    if args.bios_only:
        ok = download_cleanroom_bios(args.force)
        return 0 if ok else 1

    suites = [args.suite] if args.suite else list(ROM_MANIFEST.keys())
    total_ok, total_fail = 0, 0

    print("Downloading GBA test ROMs...\n")
    for i, name in enumerate(suites, 1):
        print(f"[{i}/{len(suites)}] {name}")
        ok, fail = download_suite(name, args.force)
        total_ok += ok
        total_fail += fail
        print()

    if args.bios or not args.suite:
        print()
        bios_ok = download_cleanroom_bios(args.force)
        if not bios_ok:
            total_fail += 1
        else:
            total_ok += 1

    print(f"Done. {total_ok} downloaded, {total_fail} failed.")
    print(f"ROMs in: {ROMS_DIR}")
    return 1 if total_fail > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
