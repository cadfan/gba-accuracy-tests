"""Runner adapter system for gba-accuracy-tests.

Each runner is a Python module in this directory that implements the Runner protocol.
Runners are discovered by scanning *.py files and looking for a RUNNER class attribute.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Runner(Protocol):
    """Protocol for emulator runners."""

    name: str

    def run_test(self, rom_path: Path, frames: int, output_path: Path) -> bool:
        """Run ROM for N frames, save screenshot to output_path.

        Returns True if the emulator ran successfully (not whether the test passed).
        Output can be .png or .bin (raw BGR555 76800 bytes).
        """
        ...

    def is_available(self) -> bool:
        """Check if this emulator is installed and accessible."""
        ...


_RUNNERS: dict[str, Runner] = {}


def _load_runner_from_file(path: Path) -> Runner | None:
    """Load a runner from a Python file."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None
    runner_cls = getattr(mod, "RUNNER", None)
    if runner_cls is None:
        return None
    return runner_cls


def discover_runners() -> dict[str, Runner]:
    """Scan runners/ directory and return available runners."""
    if _RUNNERS:
        return _RUNNERS

    runners_dir = Path(__file__).parent
    for py_file in sorted(runners_dir.glob("*.py")):
        if py_file.name.startswith("_") or py_file.name == "TEMPLATE.py":
            continue
        runner = _load_runner_from_file(py_file)
        if runner is not None and hasattr(runner, "name"):
            _RUNNERS[runner.name] = runner

    return _RUNNERS


def get_runner(name: str) -> Runner | None:
    """Get a runner by name."""
    runners = discover_runners()
    return runners.get(name)


def list_runners() -> list[str]:
    """List all available runner names."""
    return list(discover_runners().keys())
