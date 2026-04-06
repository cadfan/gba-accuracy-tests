#!/usr/bin/env python3
"""Full sweep orchestrator: run every (suite × runner × bios_mode) combination
and dump the results into references.json. Replaces the inline bash for-loop
we were using during the cable_club bring-up.

By default this is parallel-by-suite: each suite gets its own subprocess
that runs all (runner, mode) combinations serially within that suite. The
sharding is by suite because writes to suites/<suite>/references.json must
be serialized — separate suites are independent.

Usage:
    python scripts/sweep_all.py
    python scripts/sweep_all.py --suites jsmolka,armwrestler
    python scripts/sweep_all.py --runners mgba,cable_club --modes hle
    python scripts/sweep_all.py --serial      # one suite at a time
    python scripts/sweep_all.py --probe-interval 30
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUITES_DIR = REPO_ROOT / "suites"

DEFAULT_RUNNERS = ["cable_club", "mgba", "nanoboyadvance", "skyemu"]
DEFAULT_MODES = ["official", "hle", "cleanroom"]


def discover_suites() -> list[str]:
    return sorted(p.name for p in SUITES_DIR.iterdir() if p.is_dir() and (p / "manifest.toml").exists())


def run_one_suite(suite: str, runners: list[str], modes: list[str], log_path: Path) -> int:
    """Run all (runner, mode) combos for one suite, writing to log_path.
    Returns the number of (runner, mode) combos that produced at least
    one [test-id] line (a rough proxy for "succeeded")."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    succeeded = 0
    with open(log_path, "w", encoding="utf-8") as log:
        for runner in runners:
            for mode in modes:
                ts = time.strftime("%H:%M:%S")
                log.write(f"=== {ts} {runner}/{suite}/{mode} ===\n")
                log.flush()
                proc = subprocess.run(
                    [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "generate_refs.py"),
                        "--runner", runner,
                        "--suite", suite,
                        "--bios-mode", mode,
                        "--tier", "secondary",
                    ],
                    capture_output=True,
                    text=True,
                )
                wrote_any = False
                for line in (proc.stdout + proc.stderr).splitlines():
                    if "libretro" in line.lower() and "WARN" in line:
                        continue
                    log.write(line + "\n")
                    if line.lstrip().startswith("[") and "Running" not in line:
                        wrote_any = True
                if wrote_any:
                    succeeded += 1
                log.flush()
        log.write(f"=== DONE {suite} ===\n")
    return succeeded


def run_parallel(suites: list[str], runners: list[str], modes: list[str], log_dir: Path,
                 probe_interval: float, env: dict) -> int:
    children: dict[str, subprocess.Popen] = {}
    for suite in suites:
        log_path = log_dir / f"sweep-{suite}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        runners_csv = ",".join(runners)
        modes_csv = ",".join(modes)
        cmd = [
            sys.executable, str(__file__),
            "--_run_one", suite,
            "--runners", runners_csv,
            "--modes", modes_csv,
            "--log", str(log_path),
        ]
        log_handle = open(log_path.with_suffix(".driver.log"), "w", encoding="utf-8")
        children[suite] = subprocess.Popen(cmd, stdout=log_handle, stderr=subprocess.STDOUT, env=env)

    print(f"[sweep] spawned {len(children)} parallel suite jobs:")
    for s, p in children.items():
        print(f"        {s:14} pid={p.pid}")
    print()

    last_lines: dict[str, int] = {s: 0 for s in suites}
    consecutive_idle: dict[str, int] = {s: 0 for s in suites}

    while children:
        time.sleep(probe_interval)
        finished = []
        for suite, proc in list(children.items()):
            if proc.poll() is not None:
                finished.append(suite)
                continue
            log_path = log_dir / f"sweep-{suite}.log"
            try:
                lines = log_path.read_text(encoding="utf-8").count("\n") if log_path.exists() else 0
            except OSError:
                lines = 0
            if lines == last_lines[suite]:
                consecutive_idle[suite] += 1
            else:
                consecutive_idle[suite] = 0
            last_lines[suite] = lines
            tail = ""
            if log_path.exists():
                with open(log_path, "rb") as f:
                    f.seek(0, os.SEEK_END)
                    end = f.tell()
                    f.seek(max(0, end - 4096))
                    tail = f.read().decode("utf-8", errors="replace").splitlines()
                    tail = tail[-1] if tail else ""
            idle_marker = f" idle={consecutive_idle[suite]}" if consecutive_idle[suite] > 0 else ""
            print(f"[probe] {suite:14} lines={lines:4}{idle_marker}  {tail[:80]}")
        if finished:
            print()
        for s in finished:
            rc = children[s].poll()
            print(f"[done]  {s:14} rc={rc}")
            children.pop(s)
        if children and finished:
            print()

    print()
    print("[sweep] all suites finished")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the full reference sweep")
    parser.add_argument("--suites", help="Comma-separated suite names (default: all)")
    parser.add_argument("--runners", default=",".join(DEFAULT_RUNNERS),
                        help="Comma-separated runners")
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES),
                        help="Comma-separated BIOS modes")
    parser.add_argument("--serial", action="store_true",
                        help="Run one suite at a time instead of parallel")
    parser.add_argument("--probe-interval", type=float, default=30.0,
                        help="Seconds between status probes (default: 30)")
    parser.add_argument("--log-dir", default="/tmp",
                        help="Where to write per-suite logs (default: /tmp)")
    parser.add_argument("--_run_one", help=argparse.SUPPRESS)
    parser.add_argument("--log", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    runners = [r.strip() for r in args.runners.split(",") if r.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    # Internal "run one suite" mode used by the parallel parent.
    if args._run_one:
        log_path = Path(args.log) if args.log else Path(f"/tmp/sweep-{args._run_one}.log")
        run_one_suite(args._run_one, runners, modes, log_path)
        return 0

    suites = [s.strip() for s in args.suites.split(",")] if args.suites else discover_suites()
    log_dir = Path(args.log_dir)

    print(f"[sweep] suites:  {', '.join(suites)}")
    print(f"[sweep] runners: {', '.join(runners)}")
    print(f"[sweep] modes:   {', '.join(modes)}")
    print(f"[sweep] log dir: {log_dir}")
    print(f"[sweep] mode:    {'serial' if args.serial else 'parallel-by-suite'}")
    print()

    env = os.environ.copy()
    if "MGBA_BIOS_PATH" not in env and "NBA_BIOS_PATH" not in env:
        # Best-effort default: pin to the in-tree gba_bios.bin if present.
        candidate = REPO_ROOT / "runners" / "cores" / "gba_bios.bin"
        if candidate.exists():
            env["MGBA_BIOS_PATH"] = str(candidate)
            env["NBA_BIOS_PATH"] = str(candidate)
            print(f"[sweep] auto-set MGBA_BIOS_PATH/NBA_BIOS_PATH to {candidate}")

    if args.serial:
        for suite in suites:
            print(f"[serial] starting {suite}")
            run_one_suite(suite, runners, modes, log_dir / f"sweep-{suite}.log")
        return 0

    return run_parallel(suites, runners, modes, log_dir, args.probe_interval, env)


if __name__ == "__main__":
    sys.exit(main())
