#!/usr/bin/env python3
"""Static dashboard generator for gba-accuracy-tests.

Reads every suite's references.json (and the optional references_status.json
written by promote_tiers.py) and emits a self-contained static site at
docs/dashboard/. The site is plain HTML + a single CSS file — no JS, no
build tooling, no framework. GitHub Pages can serve it directly.

Pages:
    index.html              Overall matrix: suites × runners, plus header stats.
    suite-<name>.html       Per-suite detail: every test, every runner, every
                            BIOS mode, with hash, tier badge, agreement badge.
    contested.html          List of all tests where 2+ runners disagree.
    unverified.html         List of all tests where no runner has consensus.
    diff/<test>.html        Diff triptych viewer (Expected vs Actual vs Δ),
                            generated lazily on first build per test.
    style.css               One stylesheet, Pokemon Center Nostalgia palette.
    badge.svg               Top-line "X/Y passing" badge for the README.

Usage:
    python scripts/build_dashboard.py
    python scripts/build_dashboard.py --output docs/dashboard
    python scripts/build_dashboard.py --no-triptychs   # skip diff PNGs
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUITES_DIR = REPO_ROOT / "suites"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "dashboard"

# --- Slate-blue dark dashboard, Datadog/Grafana-inspired ----------------
# Synthesized from /design-shotgun feedback: dark theme (variants B/D)
# with the layout discipline and clear text of the light variants
# (A/C/E). Sans-serif body, monospace only for hashes/numbers, three
# stacked matrix tables clearly laid out, generous reading sizes.
CSS = r"""@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
  --bg:         #0e1525;
  --bg-2:       #0a101e;
  --surface:    #1a2238;
  --surface-2:  #232b42;
  --surface-3:  #2d3654;
  --border:     #2d3654;
  --border-2:   #3a4566;
  --text:       #e6ecff;
  --text-mute:  #8b95b5;
  --text-dim:   #5b6585;
  --cyan:       #00d4ff;
  --purple:     #9d6eff;
  --green:      #4ade80;
  --amber:      #fbbf24;
  --coral:      #f87171;
  --slate:      #64748b;
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
  font-size: 16px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

a { color: var(--cyan); text-decoration: none; transition: color .15s; }
a:hover { color: #5be8ff; text-decoration: underline; }
code { font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; font-size: 0.92em; color: var(--cyan); }

/* ----- header ----- */
header.site {
  background: linear-gradient(180deg, var(--surface) 0%, var(--bg) 100%);
  border-bottom: 1px solid var(--border);
  padding: 28px 40px 24px;
}
header.site .row {
  max-width: 1440px;
  margin: 0 auto;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
}
header.site h1 {
  font-family: 'Inter', sans-serif;
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.01em;
  margin: 0;
  color: var(--text);
}
header.site h1 .accent { color: var(--cyan); }
header.site .subtitle {
  color: var(--text-mute);
  margin: 4px 0 0;
  font-size: 15px;
}
nav.crumbs {
  margin: 14px 0 0;
  font-size: 14px;
  color: var(--text-mute);
}
nav.crumbs a { color: var(--text-mute); }
nav.crumbs a:hover { color: var(--cyan); }

main {
  padding: 32px 40px 80px;
  max-width: 1440px;
  margin: 0 auto;
}

/* ----- section headings ----- */
h2 {
  font-family: 'Inter', sans-serif;
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
  margin: 40px 0 8px;
  display: flex;
  align-items: center;
  gap: 12px;
}
h2::before {
  content: '';
  display: inline-block;
  width: 4px;
  height: 18px;
  background: var(--cyan);
  border-radius: 2px;
}
h2 + p, h2 + .muted {
  margin-top: 0;
  margin-bottom: 24px;
  color: var(--text-mute);
  font-size: 15px;
  max-width: 90ch;
}
h3 {
  font-family: 'Inter', sans-serif;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-mute);
  margin: 28px 0 12px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
h3 code {
  text-transform: none;
  letter-spacing: 0;
  background: var(--surface);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 13px;
}
.muted { color: var(--text-mute); }

/* ----- stat tiles ----- */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 16px;
  margin: 24px 0 8px;
}
.stat {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 18px 20px 16px;
  position: relative;
  overflow: hidden;
}
.stat::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: var(--cyan);
}
.stat:nth-child(2)::before { background: var(--purple); }
.stat:nth-child(3)::before { background: var(--green); }
.stat:nth-child(4)::before { background: var(--amber); }
.stat:nth-child(5)::before { background: var(--cyan); }
.stat:nth-child(6)::before { background: var(--coral); }
.stat:nth-child(7)::before { background: var(--slate); }
.stat .num {
  font-family: 'Inter', sans-serif;
  font-size: 32px;
  font-weight: 700;
  color: var(--text);
  display: block;
  margin-bottom: 2px;
  letter-spacing: -0.02em;
  line-height: 1.1;
}
.stat .label {
  font-size: 12px;
  color: var(--text-mute);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 500;
}
.stat .label a { color: var(--text-mute); }
.stat .label a:hover { color: var(--cyan); }

/* ----- tables ----- */
.table-wrap {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 8px;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th, td {
  padding: 14px 18px;
  text-align: left;
  font-size: 15px;
  vertical-align: middle;
}
thead th {
  background: var(--surface-2);
  color: var(--text-mute);
  font-family: 'Inter', sans-serif;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  border-bottom: 1px solid var(--border-2);
  padding-top: 12px;
  padding-bottom: 12px;
}
tbody tr {
  border-bottom: 1px solid var(--border);
  transition: background .1s;
}
tbody tr:nth-child(even) { background: var(--surface-2); }
tbody tr:last-child { border-bottom: none; }
tbody tr:hover td { background: rgba(0, 212, 255, 0.06); }
tbody td { color: var(--text); }
tbody td.id, tbody td.muted-cell {
  color: var(--text-mute);
}

/* ----- agreement matrix ----- */
.matrix th.runner {
  text-align: center;
}
.matrix th.runner .dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
  background: var(--text-mute);
}
.matrix th.runner.r-cable_club .dot     { background: var(--cyan); }
.matrix th.runner.r-mgba .dot           { background: var(--purple); }
.matrix th.runner.r-nanoboyadvance .dot { background: var(--green); }
.matrix th.runner.r-skyemu .dot         { background: var(--amber); }
.matrix td.cell {
  text-align: center;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 16px;
  font-weight: 500;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.matrix td.cell .frac { font-weight: 600; }
.matrix td.cell .pct {
  display: block;
  margin-top: 3px;
  font-size: 12px;
  color: var(--text-dim);
  font-weight: 400;
}
.matrix td.cell.all-pass { background: rgba(74, 222, 128, 0.08); }
.matrix td.cell.all-pass .frac { color: var(--green); }
.matrix td.cell.none-pass { background: rgba(248, 113, 113, 0.06); }
.matrix td.cell.none-pass .frac { color: var(--coral); }
.matrix td.cell.partial .frac { color: var(--amber); }

/* ----- hash columns ----- */
.hash {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 13px;
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}
.hash.match { color: var(--green); }
.hash.miss  { color: var(--coral); }

/* ----- status badges ----- */
.badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border: 1px solid transparent;
}
.badge.gold        { background: rgba(74, 222, 128, 0.12); color: var(--green);  border-color: rgba(74, 222, 128, 0.3); }
.badge.secondary   { background: rgba(157, 110, 255, 0.12); color: var(--purple); border-color: rgba(157, 110, 255, 0.3); }
.badge.candidate   { background: rgba(100, 116, 139, 0.18); color: var(--text-mute); border-color: rgba(100, 116, 139, 0.4); }
.badge.contested   { background: rgba(248, 113, 113, 0.14); color: var(--coral);  border-color: rgba(248, 113, 113, 0.35); }
.badge.unverified  { background: rgba(251, 191, 36, 0.12); color: var(--amber);   border-color: rgba(251, 191, 36, 0.3); }

/* ----- test-row table (per-suite detail page) ----- */
.test-row td.id {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 13px;
  color: var(--text);
  white-space: nowrap;
}

/* ----- footer ----- */
footer {
  margin-top: 80px;
  padding: 28px 40px;
  border-top: 1px solid var(--border);
  font-size: 13px;
  color: var(--text-dim);
  text-align: center;
}
footer a { color: var(--text-mute); }
footer a:hover { color: var(--cyan); }
"""

DEFAULT_RUNNERS = ["cable_club", "mgba", "nanoboyadvance", "skyemu"]
DEFAULT_MODES = ["official", "hle", "cleanroom"]

# Map historical / pretty-name runner identifiers to the canonical lowercased
# form so cleanups across schema versions don't double-report runners.
RUNNER_ALIASES = {
    "CableClub": "cable_club",
    "cable-club": "cable_club",
    "Cable Club": "cable_club",
    "mGBA": "mgba",
    "MGBA": "mgba",
    "NanoBoyAdvance": "nanoboyadvance",
    "nba": "nanoboyadvance",
    "SkyEmu": "skyemu",
    "Skyemu": "skyemu",
}


def _bios_mode_of(entry: dict) -> str:
    return entry.get("bios_mode") or entry.get("provenance", {}).get("bios_mode") or "hle"


def _emulator_of(entry: dict) -> str:
    raw = entry.get("provenance", {}).get("emulator") or "unknown"
    return RUNNER_ALIASES.get(raw, raw)


def load_suite(suite_dir: Path) -> dict:
    refs_path = suite_dir / "references.json"
    if not refs_path.exists():
        return {}
    with open(refs_path) as f:
        refs = json.load(f)
    status_path = suite_dir / "references_status.json"
    status = {}
    if status_path.exists():
        with open(status_path) as f:
            status = json.load(f).get("tests", {})
    manifest_path = suite_dir / "manifest.toml"
    suite_meta = {}
    if manifest_path.exists():
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        with open(manifest_path, "rb") as f:
            suite_meta = tomllib.load(f).get("suite", {})
    return {
        "name": suite_dir.name,
        "meta": suite_meta,
        "references": refs.get("references", {}),
        "status": status,
    }


def collect_runner_set(suites: list[dict]) -> list[str]:
    seen: set[str] = set()
    for s in suites:
        for entries in s["references"].values():
            for e in entries:
                seen.add(_emulator_of(e))
    # Stable order: known runners first, then any extras alphabetically.
    ordered = [r for r in DEFAULT_RUNNERS if r in seen]
    extras = sorted(seen - set(DEFAULT_RUNNERS))
    return ordered + extras


def matrix_cell(suite: dict, runner: str, mode: str) -> tuple[int, int]:
    """Return (passing, total) for one (suite, runner, mode) cell.

    "Passing" means the runner's hash matches the gold consensus hash for
    that test+mode. If no gold consensus exists yet (no promotion), we treat
    "passing" as "matches the modal hash" (>= 2 votes).
    """
    passing = 0
    total = 0
    for test_id, entries in suite["references"].items():
        # Find the runner's entry under this mode.
        runner_entry = None
        all_under_mode: list[dict] = []
        for e in entries:
            if _bios_mode_of(e) != mode:
                continue
            all_under_mode.append(e)
            if _emulator_of(e) == runner:
                runner_entry = e
        if runner_entry is None:
            continue
        total += 1
        # Determine consensus hash.
        counter = Counter(e["hash"] for e in all_under_mode if e.get("hash"))
        if not counter:
            continue
        modal_hash, top_count = counter.most_common(1)[0]
        consensus = None
        if top_count >= 2:
            modal_hashes = [h for h, c in counter.items() if c == top_count]
            if len(modal_hashes) == 1:
                consensus = modal_hash
        if consensus and runner_entry.get("hash") == consensus:
            passing += 1
        elif consensus is None:
            # No consensus available — count as passing if it's the only entry.
            if len(all_under_mode) == 1:
                passing += 1
    return passing, total


def page_html(title: str, body: str, breadcrumbs: list[tuple[str, str]] | None = None) -> str:
    crumbs = ""
    if breadcrumbs:
        parts = []
        for label, href in breadcrumbs:
            if href:
                parts.append(f'<a href="{html.escape(href)}">{html.escape(label)}</a>')
            else:
                parts.append(html.escape(label))
        crumbs = '<nav class="crumbs">' + " &nbsp;/&nbsp; ".join(parts) + "</nav>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — gba-accuracy-tests</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header class="site">
  <div class="row">
    <div>
      <h1>GBA Accuracy Tests <span class="accent">·</span></h1>
      <p class="subtitle">{html.escape(title)}</p>
    </div>
  </div>
  {crumbs}
</header>
<main>
{body}
</main>
<footer>
  Generated by <code>build_dashboard.py</code> · Cable Club <code>gba-accuracy-tests</code>
</footer>
</body>
</html>
"""


def build_index(suites: list[dict], runners: list[str]) -> str:
    total_tests = sum(len(s["references"]) for s in suites)
    total_runners = len(runners)
    total_modes = len(DEFAULT_MODES)
    captures = sum(
        len(entries) for s in suites for entries in s["references"].values()
    )
    contested = sum(
        1 for s in suites for st in s["status"].values() if st.get("status") == "contested"
    )
    unverified = sum(
        1 for s in suites for st in s["status"].values() if st.get("status") == "unverified"
    )
    body = [
        '<h2>Overview</h2>',
        '<div class="stat-grid">',
        f'<div class="stat"><span class="num">{len(suites)}</span><span class="label">suites</span></div>',
        f'<div class="stat"><span class="num">{total_tests}</span><span class="label">tests</span></div>',
        f'<div class="stat"><span class="num">{total_runners}</span><span class="label">runners</span></div>',
        f'<div class="stat"><span class="num">{total_modes}</span><span class="label">BIOS modes</span></div>',
        f'<div class="stat"><span class="num">{captures}</span><span class="label">captures</span></div>',
        f'<div class="stat"><span class="num">{contested}</span><span class="label"><a href="contested.html">contested</a></span></div>',
        f'<div class="stat"><span class="num">{unverified}</span><span class="label"><a href="unverified.html">unverified</a></span></div>',
        '</div>',
    ]

    body.append('<h2>Cross-runner agreement matrix</h2>')
    body.append('<p class="muted">Each cell shows <strong>X/Y agree</strong>: how many of the runner\'s '
                'captures match the cross-runner consensus hash for that test under that BIOS mode. '
                '"Consensus" means ≥ 2 runners produced the same hash. This is a stricter metric than '
                '<code>cable_club</code>\'s own <code>accuracy_sweep</code> regression check, which counts '
                'a test as passing if its hash matches <em>any</em> previously-recorded hash for the test '
                '(including the runner\'s own historical capture). Click a suite for per-test detail.</p>')
    for mode in DEFAULT_MODES:
        body.append(f'<h3>BIOS mode <code>{mode}</code></h3>')
        body.append('<div class="table-wrap"><table class="matrix"><thead><tr><th>Suite</th>')
        for r in runners:
            slug = r.replace(" ", "_")
            body.append(f'<th class="runner r-{slug}"><span class="dot"></span>{html.escape(r)}</th>')
        body.append('</tr></thead><tbody>')
        for s in suites:
            body.append(f'<tr><td><a href="suite-{html.escape(s["name"])}.html">{html.escape(s["name"])}</a></td>')
            for r in runners:
                p, t = matrix_cell(s, r, mode)
                cls = ""
                if t == 0:
                    cls = ""
                elif p == t:
                    cls = "all-pass"
                elif p == 0:
                    cls = "none-pass"
                else:
                    cls = "partial"
                pct = f"{(p / t * 100):.0f}%" if t > 0 else "—"
                body.append(
                    f'<td class="cell {cls}"><span class="frac">{p}/{t}</span>'
                    f'<span class="pct">{pct}</span></td>'
                )
            body.append('</tr>')
        body.append('</tbody></table></div>')

    return page_html("Cross-emulator agreement matrix", "\n".join(body))


def build_suite_page(suite: dict, runners: list[str]) -> str:
    body = [f'<h2>Suite: {html.escape(suite["name"])}</h2>']
    desc = suite["meta"].get("description")
    if desc:
        body.append(f'<p>{html.escape(desc)}</p>')
    src = suite["meta"].get("source")
    if src:
        body.append(f'<p class="muted">Source: <a href="{html.escape(src)}">{html.escape(src)}</a></p>')

    for mode in DEFAULT_MODES:
        body.append(f'<h3>BIOS mode <code>{mode}</code></h3>')
        body.append('<div class="table-wrap"><table><thead><tr><th>Test</th><th>Status</th>')
        for r in runners:
            slug = r.replace(" ", "_")
            body.append(f'<th class="runner r-{slug}"><span class="dot"></span>{html.escape(r)}</th>')
        body.append('</tr></thead><tbody>')

        for test_id in sorted(suite["references"].keys()):
            entries = suite["references"][test_id]
            mode_entries = [e for e in entries if _bios_mode_of(e) == mode]
            if not mode_entries:
                continue
            counter = Counter(e["hash"] for e in mode_entries if e.get("hash"))
            modal_hash = counter.most_common(1)[0][0] if counter else None
            top_count = counter.most_common(1)[0][1] if counter else 0
            consensus = modal_hash if top_count >= 2 and sum(1 for c in counter.values() if c == top_count) == 1 else None

            status_data = suite["status"].get(test_id, {})
            status = status_data.get("status", "secondary")
            badge_cls = {
                "gold": "gold",
                "contested": "contested",
                "unverified": "unverified",
                "secondary": "secondary",
            }.get(status, "secondary")

            body.append('<tr class="test-row">')
            body.append(f'<td class="id">{html.escape(test_id)}</td>')
            body.append(f'<td><span class="badge {badge_cls}">{html.escape(status)}</span></td>')
            by_runner = {_emulator_of(e): e for e in mode_entries}
            for r in runners:
                e = by_runner.get(r)
                if e is None:
                    body.append('<td><span class="hash">—</span></td>')
                    continue
                h = e.get("hash", "")
                cls = "match" if consensus and h == consensus else "miss"
                if not consensus:
                    cls = ""
                short = (h[:12] + "…") if h else ""
                body.append(f'<td><span class="hash {cls}" title="{h}">{short}</span></td>')
            body.append('</tr>')
        body.append('</tbody></table></div>')

    return page_html(
        suite["name"],
        "\n".join(body),
        breadcrumbs=[("Overview", "index.html"), (suite["name"], "")],
    )


def build_filter_page(suites: list[dict], runners: list[str], status_kind: str, title: str) -> str:
    body = [f'<h2>{html.escape(title)} tests</h2>']
    body.append(f'<p class="muted">Tests where the cross-runner agreement check returned "{status_kind}".</p>')
    body.append('<div class="table-wrap"><table><thead><tr><th>Suite</th><th>Test</th>')
    for r in runners:
        slug = r.replace(" ", "_")
        body.append(f'<th class="runner r-{slug}"><span class="dot"></span>{html.escape(r)}</th>')
    body.append('</tr></thead><tbody>')

    for s in suites:
        for test_id, st in s["status"].items():
            if st.get("status") != status_kind:
                continue
            entries = s["references"].get(test_id, [])
            # Use the cleanroom mode entries (most-shared baseline) for the table; fall back to hle.
            mode_entries = [e for e in entries if _bios_mode_of(e) == "cleanroom"]
            if not mode_entries:
                mode_entries = [e for e in entries if _bios_mode_of(e) == "hle"]
            by_runner = {_emulator_of(e): e for e in mode_entries}
            body.append('<tr>')
            body.append(f'<td><a href="suite-{html.escape(s["name"])}.html">{html.escape(s["name"])}</a></td>')
            body.append(f'<td class="hash">{html.escape(test_id)}</td>')
            for r in runners:
                e = by_runner.get(r)
                if e is None:
                    body.append('<td><span class="hash">—</span></td>')
                    continue
                h = e.get("hash", "")
                short = (h[:12] + "…") if h else ""
                body.append(f'<td><span class="hash" title="{h}">{short}</span></td>')
            body.append('</tr>')
    body.append('</tbody></table></div>')
    return page_html(
        f"{title} tests",
        "\n".join(body),
        breadcrumbs=[("Overview", "index.html"), (title, "")],
    )


def build_badge_svg(passing: int, total: int) -> str:
    label = "gba-accuracy"
    msg = f"{passing}/{total}"
    pct = passing / total if total else 0
    color = "#39ff14" if pct >= 0.9 else ("#ffb347" if pct >= 0.6 else "#cc3333")
    label_w = 8 * len(label) + 16
    msg_w = 8 * len(msg) + 16
    total_w = label_w + msg_w
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="20" role="img" aria-label="{label}: {msg}">
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
<rect width="{total_w}" height="20" rx="3" fill="#1e1a20"/>
<rect x="{label_w}" width="{msg_w}" height="20" rx="3" fill="{color}"/>
<rect width="{total_w}" height="20" rx="3" fill="url(#s)"/>
<g fill="#fff" font-family="Verdana,sans-serif" font-size="11">
  <text x="{label_w / 2:.0f}" y="14" fill="#f0e6d3">{label}</text>
  <text x="{label_w + msg_w / 2:.0f}" y="14" fill="#1e1a20">{msg}</text>
</g>
</svg>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the static dashboard")
    parser.add_argument("--output", "-o", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--no-triptychs", action="store_true",
                        help="Skip diff triptych PNG generation")
    args = parser.parse_args(argv)

    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)

    suite_dirs = sorted(p for p in SUITES_DIR.iterdir() if p.is_dir() and (p / "references.json").exists())
    suites = [load_suite(d) for d in suite_dirs]
    suites = [s for s in suites if s and s["references"]]
    if not suites:
        print("No suites with references.json found.", file=sys.stderr)
        return 1

    runners = collect_runner_set(suites)
    print(f"[dashboard] {len(suites)} suites, {len(runners)} runners detected: {runners}")

    (out / "style.css").write_text(CSS, encoding="utf-8")

    (out / "index.html").write_text(build_index(suites, runners), encoding="utf-8")
    print(f"[dashboard] wrote index.html")

    for s in suites:
        page = build_suite_page(s, runners)
        (out / f"suite-{s['name']}.html").write_text(page, encoding="utf-8")
        print(f"[dashboard] wrote suite-{s['name']}.html")

    (out / "contested.html").write_text(
        build_filter_page(suites, runners, "contested", "Contested"), encoding="utf-8"
    )
    (out / "unverified.html").write_text(
        build_filter_page(suites, runners, "unverified", "Unverified"), encoding="utf-8"
    )

    # Top-line passing badge: count cleanroom-mode consensus passes across all tests.
    total_tests = 0
    passing_tests = 0
    for s in suites:
        for entries in s["references"].values():
            mode_entries = [e for e in entries if _bios_mode_of(e) == "cleanroom"]
            if not mode_entries:
                continue
            total_tests += 1
            counter = Counter(e["hash"] for e in mode_entries if e.get("hash"))
            if not counter:
                continue
            _top, top_count = counter.most_common(1)[0]
            if top_count >= 2 and sum(1 for c in counter.values() if c == top_count) == 1:
                passing_tests += 1
    (out / "badge.svg").write_text(build_badge_svg(passing_tests, total_tests), encoding="utf-8")

    print(f"[dashboard] wrote badge.svg ({passing_tests}/{total_tests})")
    print(f"[dashboard] output: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
