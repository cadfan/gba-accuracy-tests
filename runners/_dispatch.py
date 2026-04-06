"""Runner interface v2 dispatcher.

Calls a runner's run_test() with whichever signature it supports.

v1 (legacy): run_test(rom_path, frames, output_path) -> bool
v2 (current): run_test(rom_path, frames, output_path, inputs=None, completion=None) -> bool

Detection uses inspect.signature() at first call (cached per runner instance).
This is intentional — TypeError-based dispatch was rejected because TypeError
raised inside a v2 adapter for unrelated reasons would be silently miscategorized.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

# Cache: id(runner) -> set of accepted optional kwargs ("inputs", "completion")
_SIG_CACHE: dict[int, frozenset[str]] = {}

V2_OPTIONAL_KWARGS = ("inputs", "completion")


def _accepted_v2_kwargs(runner: Any) -> frozenset[str]:
    """Inspect a runner's run_test signature and return which v2 kwargs it accepts."""
    key = id(runner)
    cached = _SIG_CACHE.get(key)
    if cached is not None:
        return cached

    accepted: set[str] = set()
    try:
        sig = inspect.signature(runner.run_test)
        params = sig.parameters
        # If the runner uses **kwargs, accept everything.
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            accepted.update(V2_OPTIONAL_KWARGS)
        else:
            for name in V2_OPTIONAL_KWARGS:
                if name in params:
                    accepted.add(name)
    except (TypeError, ValueError):
        # Can't introspect (C extension, builtin, etc.) — assume v1
        pass

    frozen = frozenset(accepted)
    _SIG_CACHE[key] = frozen
    return frozen


def dispatch_run_test(
    runner: Any,
    rom_path: Path,
    frames: int,
    output_path: Path,
    *,
    inputs: list[dict] | None = None,
    completion: dict | None = None,
) -> bool:
    """Call runner.run_test with whichever signature it supports.

    `inputs` is the manifest [[tests.input]] list (each entry is {frame, keys}).
    `completion` is the manifest [tests.completion] dict (e.g., {type, window, min_frames}).

    v1 runners (no inputs/completion params) are called with positional args only.
    v2 runners receive inputs/completion as keyword args if they accept them.
    """
    accepted = _accepted_v2_kwargs(runner)
    kwargs: dict[str, Any] = {}
    if "inputs" in accepted and inputs is not None:
        kwargs["inputs"] = inputs
    if "completion" in accepted and completion is not None:
        kwargs["completion"] = completion
    return runner.run_test(rom_path, frames, output_path, **kwargs)
