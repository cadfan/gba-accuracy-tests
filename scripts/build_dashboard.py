#!/usr/bin/env python3
"""Static dashboard generator for gba-accuracy-tests.

Reads every suite's verified.json (the human-verified canonical-hash data
source introduced by the 2026-04-07 verification arc) and emits a
self-contained static site at docs/dashboard/. The site is plain HTML +
a single CSS file -- no JS, no build tooling, no framework. GitHub Pages
can serve it directly.

Per-cell state is one of:
    pass       runner hash matches the canonical_pass_hash for that mode
    fail       runner hash differs and is annotated as expected/known wrong
               (status == "fail")
    bug        runner hash differs and is annotated as a real cable_club
               (or other runner) bug worth investigating (status == "bug")
    captured   runner produced output but no canonical pass hash exists
               yet to compare against, OR runner status == "captured"
    unverified runner status == "unverified" / no human review yet
    -          runner has no entry for this (test, mode)

Pages:
    index.html              Overall matrix: suites x runners, plus header stats
    suite-<name>.html       Per-suite detail per BIOS mode
    style.css               One stylesheet
    badge.svg               Top-line passing badge
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
.stat.s-pass::before     { background: var(--green); }
.stat.s-fail::before     { background: var(--amber); }
.stat.s-bug::before      { background: var(--coral); }
.stat.s-captured::before { background: var(--purple); }
.stat.s-unverified::before { background: var(--slate); }
.stat.s-verified::before { background: var(--green); }
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
tbody td.id, tbody td.muted-cell { color: var(--text-mute); }

.matrix th.runner { text-align: center; }
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
.matrix td.cell.all-pass { background: rgba(74, 222, 128, 0.10); }
.matrix td.cell.all-pass .frac { color: var(--green); }
.matrix td.cell.none-pass { background: rgba(248, 113, 113, 0.08); }
.matrix td.cell.none-pass .frac { color: var(--coral); }
.matrix td.cell.partial .frac { color: var(--amber); }

.hash {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 13px;
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}

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
.badge.pass       { background: rgba(74, 222, 128, 0.14); color: var(--green);    border-color: rgba(74, 222, 128, 0.35); }
.badge.fail       { background: rgba(251, 191, 36, 0.14); color: var(--amber);    border-color: rgba(251, 191, 36, 0.35); }
.badge.bug        { background: rgba(248, 113, 113, 0.16); color: var(--coral);   border-color: rgba(248, 113, 113, 0.4); }
.badge.captured   { background: rgba(157, 110, 255, 0.14); color: var(--purple);  border-color: rgba(157, 110, 255, 0.35); }
.badge.unverified { background: rgba(100, 116, 139, 0.18); color: var(--text-mute); border-color: rgba(100, 116, 139, 0.4); }
.badge.none       { background: transparent; color: var(--text-dim); border-color: var(--border); }

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 8px 0 24px;
}

.test-row td.id {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 13px;
  color: var(--text);
  white-space: nowrap;
}

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

# Per-cell normalized states.
STATE_PASS = "pass"
STATE_FAIL = "fail"
STATE_BUG = "bug"
STATE_CAPTURED = "captured"
STATE_UNVERIFIED = "unverified"
STATE_NONE = "none"

ALL_STATES = [STATE_PASS, STATE_FAIL, STATE_BUG, STATE_CAPTURED, STATE_UNVERIFIED]


def load_suite(suite_dir: Path) -> dict | None:
    verified_path = suite_dir / "verified.json"
    if not verified_path.exists():
        return None
    with open(verified_path, encoding="utf-8") as f:
        data = json.load(f)
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
        "tests": data.get("tests", {}),
    }


def cell_state(test_mode: dict, runner: str) -> tuple[str, str]:
    """Return (state, hash) for one runner under one (test, mode)."""
    runners = test_mode.get("runners", {}) or {}
    entry = runners.get(runner)
    if entry is None:
        return STATE_NONE, ""
    h = entry.get("hash", "") or ""
    raw_status = (entry.get("status") or "").lower()
    canonical = (test_mode.get("canonical_pass_hash") or "").strip()

    # Hash equality with canonical wins regardless of recorded status.
    if canonical and h and h == canonical:
        return STATE_PASS, h
    if raw_status == "pass":
        # Status says pass but no canonical to compare against.
        return STATE_PASS, h
    if raw_status == "fail":
        return STATE_FAIL, h
    if raw_status == "bug":
        return STATE_BUG, h
    if raw_status == "captured":
        return STATE_CAPTURED, h
    if raw_status == "unverified":
        return STATE_UNVERIFIED, h
    # Unknown / missing status: if we have a hash but no canonical, it's
    # captured-but-not-yet-verified.
    if h and not canonical:
        return STATE_CAPTURED, h
    if h and canonical:
        # Hash differs from canonical and no annotation -> treat as captured/unverified.
        return STATE_UNVERIFIED, h
    return STATE_UNVERIFIED, h


def collect_runner_set(suites: list[dict]) -> list[str]:
    seen: set[str] = set()
    for s in suites:
        for modes in s["tests"].values():
            for tm in modes.values():
                for r in (tm.get("runners") or {}).keys():
                    seen.add(r)
    ordered = [r for r in DEFAULT_RUNNERS if r in seen]
    extras = sorted(seen - set(DEFAULT_RUNNERS))
    return ordered + extras


def matrix_cell_counts(suite: dict, runner: str, mode: str) -> tuple[int, int, Counter]:
    """Return (passing, total, state_counter) for a (suite, runner, mode) cell.

    Total counts every test for which the runner produced an entry under the
    given mode. Passing counts only STATE_PASS.
    """
    counter: Counter = Counter()
    total = 0
    passing = 0
    for _test_id, modes in suite["tests"].items():
        tm = modes.get(mode)
        if not tm:
            continue
        state, _h = cell_state(tm, runner)
        if state == STATE_NONE:
            continue
        total += 1
        counter[state] += 1
        if state == STATE_PASS:
            passing += 1
    return passing, total, counter


def overall_state_counts(suites: list[dict], runners: list[str]) -> dict[str, int]:
    """Tally cell states across every (suite, test, mode, runner)."""
    out: Counter = Counter()
    for s in suites:
        for _test_id, modes in s["tests"].items():
            for _mode, tm in modes.items():
                for r in runners:
                    state, _h = cell_state(tm, r)
                    if state == STATE_NONE:
                        continue
                    out[state] += 1
    return dict(out)


def verification_coverage(suites: list[dict]) -> tuple[int, int]:
    """Return (verified_canonicals, total_test_modes).

    A (test, mode) is "verified" iff it has a non-empty canonical_pass_hash.
    """
    total = 0
    verified = 0
    for s in suites:
        for _test_id, modes in s["tests"].items():
            for _mode, tm in modes.items():
                total += 1
                if (tm.get("canonical_pass_hash") or "").strip():
                    verified += 1
    return verified, total


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
<title>{html.escape(title)} - gba-accuracy-tests</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header class="site">
  <div class="row">
    <div>
      <h1>GBA Accuracy Tests <span class="accent">.</span></h1>
      <p class="subtitle">{html.escape(title)}</p>
    </div>
  </div>
  {crumbs}
</header>
<main>
{body}
</main>
<footer>
  Generated by <code>build_dashboard.py</code> . Cable Club <code>gba-accuracy-tests</code> . Data source: <code>verified.json</code>
</footer>
</body>
</html>
"""


def legend_html() -> str:
    items = [
        ("pass", "pass"),
        ("fail", "fail (expected/known wrong)"),
        ("bug", "bug (real defect)"),
        ("captured", "captured (no canonical yet)"),
        ("unverified", "unverified"),
    ]
    parts = [f'<span class="badge {cls}">{html.escape(label)}</span>' for cls, label in items]
    return '<div class="legend">' + "".join(parts) + '</div>'


def build_index(suites: list[dict], runners: list[str]) -> str:
    total_tests = sum(len(s["tests"]) for s in suites)
    total_runners = len(runners)
    total_modes = len(DEFAULT_MODES)

    state_counts = overall_state_counts(suites, runners)
    verified, total_test_modes = verification_coverage(suites)
    verified_pct = f"{(verified / total_test_modes * 100):.0f}%" if total_test_modes else "-"

    body: list[str] = [
        '<h2>Overview</h2>',
        '<div class="stat-grid">',
        f'<div class="stat"><span class="num">{len(suites)}</span><span class="label">suites</span></div>',
        f'<div class="stat"><span class="num">{total_tests}</span><span class="label">tests</span></div>',
        f'<div class="stat"><span class="num">{total_runners}</span><span class="label">runners</span></div>',
        f'<div class="stat"><span class="num">{total_modes}</span><span class="label">BIOS modes</span></div>',
        f'<div class="stat s-verified"><span class="num">{verified}/{total_test_modes}</span>'
        f'<span class="label">verified canonicals ({verified_pct})</span></div>',
        '</div>',
        '<h2>Cell state breakdown</h2>',
        '<p class="muted">Counts every (suite, test, BIOS mode, runner) cell across the matrix. '
        '"pass" means the runner\'s hash matches the human-verified canonical pass hash for that '
        '(test, mode). "fail" is an annotated expected/known-wrong output. "bug" is a real defect '
        'worth investigating. "captured" is a runner output with no canonical pass hash to compare '
        'against yet. "unverified" has no human review.</p>',
        '<div class="stat-grid">',
        f'<div class="stat s-pass"><span class="num">{state_counts.get(STATE_PASS, 0)}</span><span class="label">pass</span></div>',
        f'<div class="stat s-fail"><span class="num">{state_counts.get(STATE_FAIL, 0)}</span><span class="label">fail</span></div>',
        f'<div class="stat s-bug"><span class="num">{state_counts.get(STATE_BUG, 0)}</span><span class="label">bug</span></div>',
        f'<div class="stat s-captured"><span class="num">{state_counts.get(STATE_CAPTURED, 0)}</span><span class="label">captured</span></div>',
        f'<div class="stat s-unverified"><span class="num">{state_counts.get(STATE_UNVERIFIED, 0)}</span><span class="label">unverified</span></div>',
        '</div>',
        '<h2>Pass matrix per BIOS mode</h2>',
        '<p class="muted">Each cell shows <strong>X/Y pass</strong>: how many of this runner\'s '
        'captures under this BIOS mode match the human-verified canonical pass hash. Click a suite '
        'for per-test detail.</p>',
        legend_html(),
    ]

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
                p, t, _ = matrix_cell_counts(s, r, mode)
                if t == 0:
                    cls = ""
                elif p == t:
                    cls = "all-pass"
                elif p == 0:
                    cls = "none-pass"
                else:
                    cls = "partial"
                pct = f"{(p / t * 100):.0f}%" if t > 0 else "-"
                body.append(
                    f'<td class="cell {cls}"><span class="frac">{p}/{t}</span>'
                    f'<span class="pct">{pct}</span></td>'
                )
            body.append('</tr>')
        body.append('</tbody></table></div>')

    return page_html("Verified-canonical pass matrix", "\n".join(body))


def build_suite_page(suite: dict, runners: list[str]) -> str:
    body = [f'<h2>Suite: {html.escape(suite["name"])}</h2>']
    desc = suite["meta"].get("description")
    if desc:
        body.append(f'<p>{html.escape(desc)}</p>')
    src = suite["meta"].get("source")
    if src:
        body.append(f'<p class="muted">Source: <a href="{html.escape(src)}">{html.escape(src)}</a></p>')
    body.append(legend_html())

    for mode in DEFAULT_MODES:
        body.append(f'<h3>BIOS mode <code>{mode}</code></h3>')
        body.append('<div class="table-wrap"><table><thead><tr><th>Test</th><th>Canonical</th>')
        for r in runners:
            slug = r.replace(" ", "_")
            body.append(f'<th class="runner r-{slug}"><span class="dot"></span>{html.escape(r)}</th>')
        body.append('</tr></thead><tbody>')

        for test_id in sorted(suite["tests"].keys()):
            modes = suite["tests"][test_id]
            tm = modes.get(mode)
            if not tm:
                continue
            canonical = (tm.get("canonical_pass_hash") or "").strip()
            canon_short = (canonical[:12] + "...") if canonical else ""
            canon_badge = (
                f'<span class="hash" title="{canonical}">{canon_short}</span>'
                if canonical
                else '<span class="badge unverified">none</span>'
            )

            body.append('<tr class="test-row">')
            body.append(f'<td class="id">{html.escape(test_id)}</td>')
            body.append(f'<td>{canon_badge}</td>')
            for r in runners:
                state, h = cell_state(tm, r)
                if state == STATE_NONE:
                    body.append('<td><span class="badge none">-</span></td>')
                    continue
                short = (h[:12] + "...") if h else ""
                title_attr = h or state
                body.append(
                    f'<td><span class="badge {state}" title="{title_attr}">{state}</span>'
                    f'<div class="hash" title="{h}">{short}</div></td>'
                )
            body.append('</tr>')
        body.append('</tbody></table></div>')

    return page_html(
        suite["name"],
        "\n".join(body),
        breadcrumbs=[("Overview", "index.html"), (suite["name"], "")],
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
                        help="(deprecated, ignored) skip diff triptych PNG generation")
    args = parser.parse_args(argv)

    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)

    suite_dirs = sorted(p for p in SUITES_DIR.iterdir() if p.is_dir() and (p / "verified.json").exists())
    suites = [s for s in (load_suite(d) for d in suite_dirs) if s and s["tests"]]
    if not suites:
        print("No suites with verified.json found.", file=sys.stderr)
        return 1

    runners = collect_runner_set(suites)
    print(f"[dashboard] {len(suites)} suites, {len(runners)} runners detected: {runners}")

    (out / "style.css").write_text(CSS, encoding="utf-8")
    (out / "index.html").write_text(build_index(suites, runners), encoding="utf-8")
    print("[dashboard] wrote index.html")

    for s in suites:
        page = build_suite_page(s, runners)
        (out / f"suite-{s['name']}.html").write_text(page, encoding="utf-8")
        print(f"[dashboard] wrote suite-{s['name']}.html")

    # Top-line passing badge: count cleanroom-mode pass cells across cable_club.
    passing = 0
    total = 0
    for s in suites:
        for _tid, modes in s["tests"].items():
            tm = modes.get("cleanroom")
            if not tm:
                continue
            state, _h = cell_state(tm, "cable_club")
            if state == STATE_NONE:
                continue
            total += 1
            if state == STATE_PASS:
                passing += 1
    (out / "badge.svg").write_text(build_badge_svg(passing, total), encoding="utf-8")
    print(f"[dashboard] wrote badge.svg ({passing}/{total} cable_club cleanroom pass)")
    print(f"[dashboard] output: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
