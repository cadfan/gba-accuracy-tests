"""mGBA runner adapter (libretro core).

Uses mgba_libretro.dll via runners/libretro_host.py. Replaces the previous
Lua-script-based adapter (which depended on a GUI mGBA install). Verified
against the buildbot nightly DLL — see runners/cores/mgba_libretro.sha256.

DLL discovery order:
    1. MGBA_LIBRETRO_PATH environment variable
    2. runners/cores/mgba_libretro.dll (alongside this package)
    3. Common Windows install paths (RetroArch cores dir)

BIOS handling: pass via MGBA_BIOS_PATH env var. The libretro host stages
the file as gba_bios.bin in a temp system directory and exposes it via
RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY (which is what mgba_libretro reads,
not a GET_VARIABLE option).
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from runners.libretro_host import LibretroError, LibretroSession


_HERE = Path(__file__).resolve().parent
_DEFAULT_DLL = _HERE / "cores" / "mgba_libretro.dll"
_SHA256_FILE = _HERE / "cores" / "mgba_libretro.sha256"

_COMMON_WINDOWS_PATHS = [
    Path(r"C:/RetroArch-Win64/cores/mgba_libretro.dll"),
    Path(r"C:/Program Files/RetroArch/cores/mgba_libretro.dll"),
    Path(os.path.expandvars(r"%APPDATA%/RetroArch/cores/mgba_libretro.dll")),
]


def _find_dll() -> Path | None:
    env = os.environ.get("MGBA_LIBRETRO_PATH")
    if env:
        p = Path(env)
        if p.exists():
            return p
    if _DEFAULT_DLL.exists():
        return _DEFAULT_DLL
    for p in _COMMON_WINDOWS_PATHS:
        if p.exists():
            return p
    return None


def _verify_sha256(dll_path: Path) -> None:
    """Best-effort SHA256 check against the pinned hash. Warn on mismatch."""
    if not _SHA256_FILE.exists():
        return
    try:
        pinned: str | None = None
        for line in _SHA256_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pinned = line.split()[0].lower()
            break
        if pinned is None:
            return
        actual = hashlib.sha256(dll_path.read_bytes()).hexdigest()
        if actual != pinned:
            print(
                f"[mgba runner WARN] mgba_libretro.dll sha256 {actual} "
                f"does not match pinned {pinned}; results may differ",
                file=sys.stderr,
            )
    except OSError:
        pass


class MgbaRunner:
    name = "mgba"

    def __init__(self) -> None:
        self._dll = _find_dll()
        self._bios = os.environ.get("MGBA_BIOS_PATH")
        if self._dll is not None:
            _verify_sha256(self._dll)

    def is_available(self) -> bool:
        return self._dll is not None

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
        if self._dll is None:
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # HLE mode: don't copy BIOS into the libretro system dir so the
        # mgba core falls back to its built-in HLE BIOS implementation.
        # Official mode: pass the real BIOS path.
        # BIOS selection mirrors the nanoboyadvance runner:
        #   - "official": real Nintendo BIOS from MGBA_BIOS_PATH
        #   - "cleanroom": Cult-of-GBA MIT-licensed replacement BIOS
        #     (shipped in runners/cores/gba_bios_cleanroom.bin)
        #   - "hle": no BIOS file — mgba's libretro core falls back to
        #     its built-in HLE BIOS implementation.
        cleanroom_bios = Path(__file__).resolve().parent / "cores" / "gba_bios_cleanroom.bin"
        bios_for_session: Path | None = None
        if bios_mode == "official" and self._bios is not None:
            bios_for_session = Path(self._bios)
        elif bios_mode == "cleanroom" and cleanroom_bios.exists():
            bios_for_session = cleanroom_bios
        try:
            session = LibretroSession(
                self._dll,
                bios_path=bios_for_session,
                bios_filename="gba_bios.bin",
            )
            try:
                raw = session.run_capture(
                    rom_path,
                    target_frames=frames,
                    inputs=inputs,
                    completion=completion,
                )
            finally:
                session.cleanup()
        except LibretroError as e:
            print(f"[mgba runner] {e}", file=sys.stderr)
            return False
        except OSError as e:
            print(f"[mgba runner] {e}", file=sys.stderr)
            return False

        try:
            output_path.write_bytes(raw)
        except OSError as e:
            print(f"[mgba runner] write {output_path}: {e}", file=sys.stderr)
            return False
        return True


RUNNER = MgbaRunner()
