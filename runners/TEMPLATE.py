"""TEMPLATE: Runner adapter for gba-accuracy-tests.

Copy this file to runners/<your-emulator>.py and implement the methods.
See README.md for full documentation.

Required:
- A class with `name`, `is_available()`, and `run_test()` methods
- A module-level RUNNER instance
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class MyEmulatorRunner:
    name = "my-emulator"  # Used as --runner value in compare.py

    def is_available(self) -> bool:
        """Check if the emulator binary is installed."""
        return shutil.which("my-emulator") is not None

    def run_test(self, rom_path: Path, frames: int, output_path: Path) -> bool:
        """Run ROM for N frames, save screenshot to output_path.

        Returns True if the emulator ran successfully.
        Output must be a PNG (240x160) or raw BGR555 .bin (76800 bytes).
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "my-emulator",
            "--headless",
            str(rom_path),
            "--frames", str(frames),
            "--screenshot", str(output_path),
        ]

        try:
            result = subprocess.run(cmd, timeout=60, capture_output=True)
            return result.returncode == 0 and output_path.exists()
        except (subprocess.TimeoutExpired, OSError):
            return False


# Module-level instance — compare.py discovers this
RUNNER = MyEmulatorRunner()
