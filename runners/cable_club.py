"""Cable Club runner adapter.

Uses Cable Club's accuracy-sweep binary to run ROMs headlessly.
Expects the Cable Club repo to be available with a built accuracy-sweep binary.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class CableClubRunner:
    name = "cable-club"

    def __init__(self) -> None:
        self._exe = shutil.which("accuracy-sweep")

    def is_available(self) -> bool:
        return self._exe is not None

    def run_test(
        self,
        rom_path: Path,
        frames: int,
        output_path: Path,
        *,
        inputs: list[dict] | None = None,
        completion: dict | None = None,
    ) -> bool:
        if self._exe is None:
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self._exe,
            str(rom_path),
            "--frames", str(frames),
            "--screenshot", str(output_path),
        ]
        if inputs:
            # Forward as --keys frame:mask,frame:mask,...
            keyspec = ",".join(f"{i['frame']}:{i['keys']}" for i in inputs)
            cmd += ["--keys", keyspec]
        # `completion` ignored — accuracy-sweep currently uses fixed frame count.

        try:
            result = subprocess.run(cmd, timeout=60, capture_output=True)
            return result.returncode == 0 and output_path.exists()
        except subprocess.TimeoutExpired:
            return False
        except OSError:
            return False


RUNNER = CableClubRunner()
