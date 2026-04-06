"""Cable Club runner adapter (headless capture binary).

Invokes target/release/cable-club-runner — Cable Club's own headless
capture binary, built from crates/cable-club-tests/src/bin/cable_club_runner.rs.
The binary mirrors the nba-headless CLI so this adapter is a thin
subprocess wrapper just like nanoboyadvance.py.

Discovery (in order):
    1. CABLE_CLUB_RUNNER_PATH env var
    2. <repo_root>/target/release/cable-club-runner[.exe]
    3. PATH lookup
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# This file lives at <repo_root>/tests/gba-accuracy-tests/runners/cable_club.py
_HERE = Path(__file__).resolve().parent
# runners → tests/gba-accuracy-tests → tests → repo root
_REPO_ROOT = _HERE.parent.parent.parent
_BIN_NAME = "cable-club-runner.exe" if os.name == "nt" else "cable-club-runner"
_DEFAULT = _REPO_ROOT / "target" / "release" / _BIN_NAME
_CLEANROOM_BIOS = _HERE / "cores" / "gba_bios_cleanroom.bin"


def _find_runner() -> Path | None:
    env = os.environ.get("CABLE_CLUB_RUNNER_PATH")
    if env and Path(env).exists():
        return Path(env)
    if _DEFAULT.exists():
        return _DEFAULT
    found = shutil.which("cable-club-runner")
    return Path(found) if found else None


class CableClubRunner:
    name = "cable_club"

    def __init__(self) -> None:
        self._exe = _find_runner()
        self._bios = os.environ.get("CABLE_CLUB_BIOS_PATH") or os.environ.get("MGBA_BIOS_PATH")

    def is_available(self) -> bool:
        # Cable Club doesn't strictly need a Nintendo BIOS — its HLE path
        # works without one — so the binary alone is enough.
        return self._exe is not None

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
        del completion  # cable-club-runner captures the final frame; harness completion
                        # logic lives in cable_club's own accuracy_sweep, not in this CLI
        if self._exe is None:
            return False

        # BIOS selection mirrors the other runners:
        #   - "official": pass --bios <real Nintendo>. Loads real BIOS data
        #     into cable_club_core for SWI/latch correctness AND boots
        #     through the BIOS animation.
        #   - "cleanroom": pass --bios <Cult-of-GBA>. Same path, different blob.
        #   - "hle": no --bios flag (or --skip-bios). cable_club uses its
        #     internal HLE; if a real BIOS is available on its search path
        #     it loads it for SWI but skips boot. This is its standard mode.
        bios_for_run: Path | None = None
        if bios_mode == "official":
            if self._bios and Path(self._bios).exists():
                bios_for_run = Path(self._bios)
        elif bios_mode == "cleanroom":
            if _CLEANROOM_BIOS.exists():
                bios_for_run = _CLEANROOM_BIOS

        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(self._exe),
            "--rom", str(rom_path),
            "--output", str(output_path),
            "--frames", str(frames),
        ]
        if bios_for_run is not None:
            cmd += ["--bios", str(bios_for_run)]
        if bios_mode in ("hle", "skip"):
            cmd.append("--skip-bios")
        if inputs:
            cmd += ["--keys", ",".join(f"{int(i['frame'])}:{int(i['keys'])}" for i in inputs)]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            _, stderr = proc.communicate(timeout=300.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            print("[cable_club runner] timeout after 300s", file=sys.stderr)
            return False

        if proc.returncode != 0:
            print(f"[cable_club runner] exit {proc.returncode}: {stderr.decode(errors='replace')}",
                  file=sys.stderr)
            return False
        return output_path.exists() and output_path.stat().st_size == 76800


RUNNER = CableClubRunner()
