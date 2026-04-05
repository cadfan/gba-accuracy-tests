"""NanoBoyAdvance runner adapter.

Uses NanoBoyAdvance's headless mode to run ROMs and capture screenshots.
NanoBoyAdvance is a cycle-accurate GBA emulator.

CLI: NanoBoyAdvance.exe --headless --frames N --screenshot output.png rom.gba
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class NanoBoyAdvanceRunner:
    name = "nanoboyadvance"

    def __init__(self) -> None:
        self._exe = self._find_nba()
        self._bios = self._find_bios()

    def _find_nba(self) -> str | None:
        # Check env var first
        env_path = os.environ.get("NBA_PATH")
        if env_path:
            p = Path(env_path)
            if p.exists():
                return str(p)

        # Check PATH
        exe = shutil.which("NanoBoyAdvance")
        if exe:
            return exe

        # Common Windows install paths
        for candidate in [
            Path("C:/tools/NanoBoyAdvance/NanoBoyAdvance.exe"),
            Path("C:/Program Files/NanoBoyAdvance/NanoBoyAdvance.exe"),
            Path("C:/Program Files (x86)/NanoBoyAdvance/NanoBoyAdvance.exe"),
        ]:
            if candidate.exists():
                return str(candidate)

        return None

    def _find_bios(self) -> str | None:
        env_path = os.environ.get("NBA_BIOS_PATH")
        if env_path:
            p = Path(env_path)
            if p.exists():
                return str(p)
        return None

    def is_available(self) -> bool:
        return self._exe is not None

    def run_test(self, rom_path: Path, frames: int, output_path: Path) -> bool:
        if self._exe is None:
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self._exe,
            "--headless",
            "--frames", str(frames),
            "--screenshot", str(output_path),
        ]

        if self._bios:
            cmd.extend(["--bios", self._bios])

        cmd.append(str(rom_path))

        try:
            result = subprocess.run(cmd, timeout=120, capture_output=True)
            return result.returncode == 0 and output_path.exists()
        except subprocess.TimeoutExpired:
            return False
        except OSError:
            return False


RUNNER = NanoBoyAdvanceRunner()
