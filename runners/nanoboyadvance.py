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
        return self._exe is not None and self._bios is not None and Path(self._bios).exists()

    def run_test(
        self,
        rom_path: Path,
        frames: int,
        output_path: Path,
        *,
        inputs: list[dict] | None = None,
        completion: dict | None = None,
    ) -> bool:
        del completion
        if self._exe is None or self._bios is None:
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(self._exe),
            "--rom", str(rom_path),
            "--bios", str(self._bios),
            "--frames", str(frames),
            "--output", str(output_path),
        ]
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
