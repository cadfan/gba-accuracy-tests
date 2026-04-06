#!/usr/bin/env python3
"""Empirically promote reference entries to gold/secondary/contested tiers
based on cross-emulator agreement, replacing the schema's generic
GBAHawk > Mesen > NBA > mgba heuristic.

Promotion rule (default):
    For each (test, bios_mode), look at the unique set of hashes across all
    runners that produced a result.
      - If N >= 2 runners agree on hash H AND H is the modal hash, every
        entry with hash H gets tier "gold" (it's the consensus answer).
      - All other entries stay "secondary".
      - If only one runner produced a result for that (test, bios_mode),
        the entry stays at its original tier (no promotion possible).

Marks two derived statuses on the suite-level metadata:
    - "contested": tests where two or more distinct hashes have >= 2 votes
    - "unverified": tests where no hash has >= 2 votes
These statuses are written to a sibling file `references_status.json`
keyed by test_id so the dashboard can render them without re-deriving
from references.json.

Usage:
    python scripts/promote_tiers.py                   # all suites
    python scripts/promote_tiers.py --suite jsmolka   # one suite
    python scripts/promote_tiers.py --dry-run         # show, don't write
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUITES_DIR = REPO_ROOT / "suites"

GOLD = "gold"
SECONDARY = "secondary"
CANDIDATE = "candidate"
MIN_VOTES_FOR_GOLD = 2


def _bios_mode_of(entry: dict) -> str:
    return entry.get("bios_mode") or entry.get("provenance", {}).get("bios_mode") or "hle"


def promote_suite(suite_dir: Path, dry_run: bool = False) -> dict:
    refs_path = suite_dir / "references.json"
    if not refs_path.exists():
        return {"suite": suite_dir.name, "skipped": True}
    with open(refs_path) as f:
        refs = json.load(f)
    references = refs.get("references", {})

    gold_count = 0
    secondary_count = 0
    contested = []
    unverified = []
    test_status: dict[str, dict] = {}

    for test_id, entries in references.items():
        # Group by bios_mode so we don't compare across modes.
        by_mode: dict[str, list[dict]] = defaultdict(list)
        for e in entries:
            by_mode[_bios_mode_of(e)].append(e)

        # Per-test status across modes — derived from the WORST mode.
        any_gold = False
        any_contested = False
        any_unverified = False

        for mode_entries in by_mode.values():
            counter = Counter(e["hash"] for e in mode_entries if e.get("hash"))
            if not counter:
                continue
            most_common, top_count = counter.most_common(1)[0]
            distinct = list(counter.items())

            modal_hashes = {h for h, c in distinct if c >= MIN_VOTES_FOR_GOLD}
            if len(modal_hashes) > 1:
                any_contested = True
            elif top_count < MIN_VOTES_FOR_GOLD:
                any_unverified = True
            elif top_count >= MIN_VOTES_FOR_GOLD:
                any_gold = True

            for e in mode_entries:
                h = e.get("hash")
                if h is None:
                    continue
                if top_count >= MIN_VOTES_FOR_GOLD and h == most_common and len(modal_hashes) == 1:
                    if e.get("tier") != GOLD:
                        e["tier"] = GOLD
                        gold_count += 1
                else:
                    if e.get("tier") == GOLD:
                        e["tier"] = SECONDARY
                    if e.get("tier") not in (GOLD, CANDIDATE):
                        e["tier"] = SECONDARY
                    secondary_count += 1

        if any_contested:
            contested.append(test_id)
            test_status[test_id] = {"status": "contested"}
        elif any_unverified and not any_gold:
            unverified.append(test_id)
            test_status[test_id] = {"status": "unverified"}
        elif any_gold:
            test_status[test_id] = {"status": "gold"}
        else:
            test_status[test_id] = {"status": "secondary"}

    if not dry_run:
        with open(refs_path, "w") as f:
            json.dump(refs, f, indent=2)
        status_path = suite_dir / "references_status.json"
        with open(status_path, "w") as f:
            json.dump({"tests": test_status}, f, indent=2)

    return {
        "suite": suite_dir.name,
        "tests": len(references),
        "gold_entries": gold_count,
        "secondary_entries": secondary_count,
        "contested": contested,
        "unverified": unverified,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Promote reference tiers by cross-runner agreement")
    parser.add_argument("--suite", "-s", help="Promote one suite only")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Show changes, don't write")
    args = parser.parse_args(argv)

    suites: list[Path]
    if args.suite:
        suites = [SUITES_DIR / args.suite]
    else:
        suites = sorted(p for p in SUITES_DIR.iterdir() if p.is_dir())

    print(f"Promoting tiers across {len(suites)} suite(s)" + (" (dry-run)" if args.dry_run else ""))
    print()
    total_contested = 0
    total_unverified = 0
    for s in suites:
        result = promote_suite(s, dry_run=args.dry_run)
        if result.get("skipped"):
            continue
        cn = len(result["contested"])
        un = len(result["unverified"])
        total_contested += cn
        total_unverified += un
        print(f"  [{result['suite']:14}] tests={result['tests']:3}  gold-entries={result['gold_entries']:4}  contested={cn:2}  unverified={un:2}")
        if cn:
            for t in result["contested"]:
                print(f"      contested: {t}")
        if un:
            for t in result["unverified"]:
                print(f"      unverified: {t}")
    print()
    print(f"Totals: contested={total_contested}, unverified={total_unverified}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
