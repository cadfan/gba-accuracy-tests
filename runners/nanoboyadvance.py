"""NanoBoyAdvance runner adapter (headless capture binary).

Invokes nba-headless.exe (built from cadfan/NanoBoyAdvance:feat/headless-capture
or pre-built and pinned in runners/cores/). Headless binary writes raw
BGR555 LE directly — no PNG conversion needed.

Discovery:
    1. NBA_HEADLESS_PATH env var
    2. runners/cores/nba-headless.exe
    3. PATH lookup
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DEFAULT = _HERE / "cores" / ("nba-headless.exe" if os.name == "nt" else "nba-headless")
_SHA256_FILE = _HERE / "cores" / "nba_headless.sha256"
_CLEANROOM_BIOS = _HERE / "cores" / "gba_bios_cleanroom.bin"


def _find_nba() -> Path | None:
    env = os.environ.get("NBA_HEADLESS_PATH")
    if env and Path(env).exists():
        return Path(env)
    if _DEFAULT.exists():
        return _DEFAULT
    found = shutil.which("nba-headless")
    return Path(found) if found else None


def _verify_sha256(p: Path) -> None:
    if not _SHA256_FILE.exists():
        return
    try:
        for line in _SHA256_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pinned = line.split()[0].lower()
                actual = hashlib.sha256(p.read_bytes()).hexdigest()
                if actual != pinned:
                    print(
                        f"[nba runner WARN] nba-headless sha256 {actual} "
                        f"does not match pinned {pinned}",
                        file=sys.stderr,
                    )
                return
    except OSError:
        pass


class NanoBoyAdvanceRunner:
    name = "nanoboyadvance"

    def __init__(self) -> None:
        self._exe = _find_nba()
        self._bios = os.environ.get("NBA_BIOS_PATH") or os.environ.get("MGBA_BIOS_PATH")
        if self._exe is not None:
            _verify_sha256(self._exe)

    def is_available(self) -> bool:
        if self._exe is None:
            return False
        has_real_bios = self._bios is not None and Path(self._bios).exists()
        has_cleanroom = _CLEANROOM_BIOS.exists()
        return has_real_bios or has_cleanroom

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
        del completion
        if self._exe is None:
            return False

        # Select BIOS file based on mode:
        #   - "official": user-provided real Nintendo BIOS (NBA_BIOS_PATH /
        #     MGBA_BIOS_PATH). Highest accuracy.
        #   - "cleanroom": Cult-of-GBA MIT-licensed replacement BIOS.
        #     Distributable. Behaves like a real 16KB BIOS blob.
        #   - "hle"/"skip": real BIOS file is still loaded (NBA has no true
        #     HLE BIOS), but --skip-bios tells the core to jump past the
        #     boot animation. If no real BIOS is available, falls back to
        #     cleanroom to keep the test runnable.
        if bios_mode == "cleanroom":
            bios_file: Path | None = _CLEANROOM_BIOS if _CLEANROOM_BIOS.exists() else None
        elif bios_mode == "official":
            bios_file = Path(self._bios) if self._bios else None
        else:  # hle / skip
            if self._bios:
                bios_file = Path(self._bios)
            elif _CLEANROOM_BIOS.exists():
                bios_file = _CLEANROOM_BIOS
            else:
                bios_file = None

        if bios_file is None or not bios_file.exists():
            print(f"[nba runner] no BIOS available for mode={bios_mode}", file=sys.stderr)
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(self._exe),
            "--rom", str(rom_path),
            "--bios", str(bios_file),
            "--frames", str(frames),
            "--output", str(output_path),
        ]
        if bios_mode in ("hle", "skip"):
            cmd.append("--skip-bios")
        if inputs:
            cmd += ["--keys", ",".join(f"{int(i['frame'])}:{int(i['keys'])}" for i in inputs)]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            _, stderr = proc.communicate(timeout=120.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            print("[nba runner] timeout after 120s", file=sys.stderr)
            return False

        if proc.returncode != 0:
            print(f"[nba runner] exit {proc.returncode}: {stderr.decode(errors='replace')}",
                  file=sys.stderr)
            return False
        return output_path.exists() and output_path.stat().st_size == 76800


RUNNER = NanoBoyAdvanceRunner()
