"""TEMPLATE: Runner adapter for gba-accuracy-tests.

Copy this file to runners/<your-emulator>.py and implement the methods.
See README.md for full documentation.

Required:
- A class with `name`, `is_available()`, and `run_test()` methods
- A module-level RUNNER instance

Runner interface v2 (current):
    run_test(rom_path, frames, output_path, *, inputs=None, completion=None) -> bool

`inputs` is the manifest [[tests.input]] list. Each entry is a dict like
{"frame": 5, "keys": 8} where `keys` is a libretro/GBA-style button bitmask.
Implementations that don't need input injection can ignore it.

`completion` is the manifest [tests.completion] dict, e.g.
{"type": "input_then_stable", "window": 15, "min_frames": 30}. Implementations
that don't need adaptive completion can ignore it.

v1 adapters that take only (rom_path, frames, output_path) still work — the
dispatcher inspects the signature and calls them positionally.
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

    def run_test(
        self,
        rom_path: Path,
        frames: int,
        output_path: Path,
        *,
        inputs: list[dict] | None = None,
        completion: dict | None = None,
    ) -> bool:
        """Run ROM for N frames, save screenshot to output_path.

        Returns True if the emulator ran successfully.
        Output must be a PNG (240x160) or raw BGR555 .bin (76800 bytes).

        v2 params:
            inputs: optional [{frame: int, keys: int}, ...] for timed key injection
            completion: optional {type, window, min_frames} for adaptive stop
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "my-emulator",
            "--headless",
            str(rom_path),
            "--frames", str(frames),
            "--screenshot", str(output_path),
        ]
        # Example: forward inputs as --keys frame:mask,frame:mask,...
        if inputs:
            keyspec = ",".join(f"{i['frame']}:{i['keys']}" for i in inputs)
            cmd += ["--keys", keyspec]

        try:
            result = subprocess.run(cmd, timeout=120, capture_output=True)
            return result.returncode == 0 and output_path.exists()
        except (subprocess.TimeoutExpired, OSError):
            return False


# Module-level instance — compare.py discovers this
RUNNER = MyEmulatorRunner()
