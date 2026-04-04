"""mGBA runner adapter.

Uses mGBA's Lua scripting (mgba-capture.lua) to run ROMs headlessly
and capture framebuffer screenshots.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class MgbaRunner:
    name = "mgba"

    def __init__(self) -> None:
        self._exe = self._find_mgba()
        self._lua_script = Path(__file__).resolve().parent.parent / "scripts" / "mgba_capture.lua"

    def _find_mgba(self) -> str | None:
        exe = shutil.which("mgba-qt") or shutil.which("mgba")
        if exe:
            return exe
        # Common Windows install path
        win_path = Path("C:/Program Files/mGBA/mGBA.exe")
        if win_path.exists():
            return str(win_path)
        return None

    def is_available(self) -> bool:
        return self._exe is not None and self._lua_script.exists()

    def run_test(self, rom_path: Path, frames: int, output_path: Path) -> bool:
        if self._exe is None:
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["MGBA_FRAMES"] = str(frames)
        env["MGBA_OUTPUT"] = str(output_path)

        cmd = [self._exe, "-l", str(self._lua_script), str(rom_path)]

        try:
            result = subprocess.run(
                cmd,
                timeout=60,
                capture_output=True,
                env=env,
            )
            return output_path.exists() and output_path.stat().st_size > 0
        except subprocess.TimeoutExpired:
            return False
        except OSError:
            return False


RUNNER = MgbaRunner()
