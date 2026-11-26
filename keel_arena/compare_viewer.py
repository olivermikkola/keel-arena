"""Offline local compare shell: load results, summarize, write cards, serve HTML.

Wraps validate/report/cards and keel_mobile.compare_runs. No model calls, no
orchestration engine, no network egress beyond an optional loopback HTTP server.
"""

from __future__ import annotations

import html
import json
import socket
import threading
import webbrowser
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .cards import write_cards
from .keel_mobile import compare_runs, load_run, parse_setup_pairs
from .results import InvalidResult, load, require, summarize

OUTCOME_ORDER = ("solved", "unsolved", "timeout", "infrastructure_error")


def _esc(value):
    return html.escape(str(value), quote=True)


def _short_digest(value, n=12):
    text = str(value or "")
    if len(text) <= n:
        return text
    return text[:n]


def _fmt_rate(value):
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _outcome_counts(outcomes):
    raw = outcomes or {}
    return {key: int(raw.get(key, 0)) for key in OUTCOME_ORDER}


def _purpose_class(purpose):
    return "badge-demo" if purpose == "demonstration" else "badge-bench"


def detect_run_kind(path):
    """Classify a path as Arena results JSON or a Keel Mobile run artifact."""
    target = Path(path)
    require(not target.is_symlink(), "symlinked compare path refused")
    require(target.exists(), "compare path does not exist")
    if target.is_dir() or target.suffix == ".jsonl":
        return "keel_mobile"
    if target.is_file() and target.suffix == ".json":
        return "arena_results"
    raise InvalidResult("compare path must be results JSON, a Keel Mobile run dir, or .jsonl")


def _shared_css():
    return """
:root {
  --bg: #0a1112;
  --panel: #101a1c;
  --line: #22363a;
  --text: #eef4f2;
  --muted: #8ca3a0;
  --teal: #36b394;
  --coral: #dc7648;
  --cream: #f7f3e9;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 24px;
  background: radial-gradient(1200px 600px at 10% -10%, #143038 0%, var(--bg) 55%);
  color: var(--text);
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
  line-height: 1.45;
}
.wrap { max-width: 1100px; margin: 0 auto; }
header { display: flex; flex-wrap: wrap; gap: 12px 18px; align-items: baseline; margin-bottom: 18px; }
h1 { margin: 0; font-size: 1.6rem; color: var(--cream); letter-spacing: 0.02em; }
h1 span { color: var(--teal); }
.badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.badge-demo { background: #3a2a18; color: #f0c48a; border: 1px solid #6a4a22; }
.badge-bench { background: #12332c; color: #8fe0c8; border: 1px solid #2a6a58; }
.meta { color: var(--muted); font-size: 0.92rem; margin-bottom: 18px; }
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 16px;
  margin: 14px 0;
}
h2 { margin: 0 0 12px; font-size: 1.05rem; color: var(--cream); }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th, td { padding: 8px 10px; border-bottom: 1px solid #1a2b2e; text-align: left; vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
td.ok { color: var(--teal); font-variant-numeric: tabular-nums; }
td.warn { color: #e5a95e; font-variant-numeric: tabular-nums; }
td.infra { color: var(--coral); font-variant-numeric: tabular-nums; }
td.num { font-variant-numeric: tabular-nums; }
code { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 0.85rem; }
.actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; }
a.button {
  display: inline-block;
  padding: 10px 14px;
  background: var(--teal);
  color: #041210;
  text-decoration: none;
  border-radius: 8px;
  font-weight: 700;
}
a.button.secondary { background: transparent; color: var(--text); border: 1px solid var(--line); }
.note { color: var(--muted); font-size: 0.85rem; margin-top: 10px; }
.warnings { color: #e5a95e; }
.warnings li { margin: 4px 0; }
.empty { color: var(--muted); font-style: italic; }
"""


def render_compare_html(data, report, *, dashboard_href="cards/dashboard.html", source_label="results.json"):
    """Render a single-page compare shell from validated results + summarize()."""
    protocol = data["protocol"]
    purpose = report["purpose"]
    purpose_class = _purpose_class(purpose)
    contestant_rows = []
    for name in sorted(report["contestants"]):
        row = report["contestants"][name]
        counts = _outcome_counts(row.get("outcomes"))
        contestant_rows.append(
            "<tr>"
            f"<td><strong>{_esc(name)}</strong></td>"
            f"<td>{_esc(row.get('quantization') or 'unknown')}</td>"
            f"<td>{_esc(row.get('harness') or 'keel')}</td>"
            f"<td>{_esc(row.get('grade', 'N/A'))}</td>"
            f"<td>{_fmt_rate(row.get('matched_task_mean_solve_rate'))}</td>"
            f"<td>{row['matched_solved']}/{row['matched_attempts']}</td>"
            f"<td class='ok'>{counts['solved']}</td>"
            f"<td>{counts['unsolved']}</td>"
            f"<td class='warn'>{counts['timeout']}</td>"
            f"<td class='infra'>{counts['infrastructure_error']}</td>"
            "</tr>"
        )

    digest_rows = [
        ("result_sha256", report["result_sha256"]),
        ("harness_revision", protocol["harness_revision"]),
        ("environment_sha256", protocol["environment_sha256"]),
        ("sampling_sha256", protocol["sampling_sha256"]),
    ]
    digest_html = "".join(
        f"<tr><th>{_esc(label)}</th><td><code title='{_esc(value)}'>{_esc(_short_digest(value))}</code></td></tr>"
        for label, value in digest_rows
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Keel Arena Compare</title>
<style>{_shared_css()}</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Keel <span>Arena</span> Compare</h1>
    <span class="badge {purpose_class}">{_esc(purpose)}</span>
  </header>
  <p class="meta">
    Source: <code>{_esc(source_label)}</code> ·
    Tasks: {report['independent_tasks']} ·
    Matched blocks: {report['matched_blocks']}/{report['planned_blocks']} ·
    Excluded (infra): {report['excluded_blocks']}
  </p>

  <section class="panel">
    <h2>Provenance digests</h2>
    <table>
      <tbody>{digest_html}</tbody>
    </table>
    <p class="note">Pin these digests before comparing runs. Verifier bodies and private traces stay out of this view.</p>
  </section>

  <section class="panel">
    <h2>Contestants &amp; outcomes</h2>
    <table>
      <thead>
        <tr>
          <th>Contestant</th><th>Quant</th><th>Harness</th><th>Grade</th>
          <th>Task mean</th><th>Solved / matched</th>
          <th>solved</th><th>unsolved</th><th>timeout</th><th>infra</th>
        </tr>
      </thead>
      <tbody>
        {''.join(contestant_rows)}
      </tbody>
    </table>
  </section>

  <section class="panel">
    <h2>Cards &amp; dashboard</h2>
    <p class="meta" style="margin:0 0 8px">Offline SVG cards and <code>dashboard.html</code> from <code>keel_arena.cards</code>.</p>
    <div class="actions">
      <a class="button" href="{_esc(dashboard_href)}" target="_blank" rel="noopener">Open dashboard.html</a>
      <a class="button secondary" href="cards/overview.svg" target="_blank" rel="noopener">Overview SVG</a>
    </div>
  </section>
</div>
</body>
</html>
"""


def compare_arena_results(left_data, right_data, *, left_label="left", right_label="right"):
    """Paired outcome-matrix diff over two validated Arena results documents."""
    left_report = summarize(left_data)
    right_report = summarize(right_data)
    left_map = {
        (row["task"], row["contestant"], row["repetition"]): row["outcome"]
        for row in left_data["attempts"]
    }
    right_map = {
        (row["task"], row["contestant"], row["repetition"]): row["outcome"]
        for row in right_data["attempts"]
    }
    common = sorted(set(left_map) & set(right_map))
    left_only = sorted(set(left_map) - set(right_map))
    right_only = sorted(set(right_map) - set(left_map))
    warnings = []
    if left_only or right_only:
        warnings.append(
            f"{len(left_only) + len(right_only)} attempt cells are recorded on one side only and are not compared"
        )
    if left_data["purpose"] != right_data["purpose"]:
        warnings.append("purpose labels differ between runs; keep demonstration fixtures labeled")
    if left_data["purpose"] == "demonstration" or right_data["purpose"] == "demonstration":
        warnings.append("at least one side is purpose=demonstration; not a measured model result")

    setup_differences = []
    for field in ("harness_revision", "environment_sha256", "sampling_sha256"):
        a, b = left_data["protocol"][field], right_data["protocol"][field]
        if a != b:
            setup_differences.append({"field": field, "left": a, "right": b})
    if left_report["result_sha256"] != right_report["result_sha256"]:
        setup_differences.append(
            {
                "field": "result_sha256",
                "left": left_report["result_sha256"],
                "right": right_report["result_sha256"],
            }
        )
    if not setup_differences:
        warnings.append(
            "no recorded protocol or result digest difference: score changes cannot be attributed to a setup"
        )

    excluded = [
        key for key in common
        if "infrastructure_error" in (left_map[key], right_map[key])
    ]
    matched = [key for key in common if key not in excluded]

    def totals(side_map):
        outcomes = Counter(side_map[key] for key in matched)
        solved = outcomes.get("solved", 0)
        return {
            "attempts": len(matched),
            "solved": solved,
            "solve_rate": (solved / len(matched)) if matched else None,
            "outcomes": {name: int(outcomes.get(name, 0)) for name in OUTCOME_ORDER[:3]},
        }

    left_totals, right_totals = totals(left_map), totals(right_map)
    paired = Counter()
    for key in matched:
        a_solved = left_map[key] == "solved"
        b_solved = right_map[key] == "solved"
        if a_solved and b_solved:
            paired["both_solved"] += 1
        elif a_solved:
            paired["left_only_solved"] += 1
        elif b_solved:
            paired["right_only_solved"] += 1
        else:
            paired["neither_solved"] += 1

    tasks = {}
    for task, contestant, repetition in matched:
        entry = tasks.setdefault(
            (task, contestant),
            {
                "task": task,
                "contestant": contestant,
                "attempts": 0,
                "left_solved": 0,
                "right_solved": 0,
                "samples": [],
            },
        )
        entry["attempts"] += 1
        left_outcome = left_map[(task, contestant, repetition)]
        right_outcome = right_map[(task, contestant, repetition)]
        entry["left_solved"] += left_outcome == "solved"
        entry["right_solved"] += right_outcome == "solved"
        if left_outcome != right_outcome:
            entry["samples"].append(
                {
                    "repetition": repetition,
                    "left": left_outcome,
                    "right": right_outcome,
                }
            )
    changed = []
    for entry in tasks.values():
        entry["difference"] = entry["right_solved"] - entry["left_solved"]
        if entry["samples"]:
            changed.append(entry)
    changed.sort(
        key=lambda e: (-abs(e["difference"]), e["difference"], e["task"], e["contestant"])
    )
    timeouts = [
        {
            "task": task,
            "contestant": contestant,
            "repetition": repetition,
            "left": left_map[(task, contestant, repetition)],
            "right": right_map[(task, contestant, repetition)],
        }
        for task, contestant, repetition in matched
        if "timeout" in (
            left_map[(task, contestant, repetition)],
            right_map[(task, contestant, repetition)],
        )
    ]
    infra = [
        {
            "task": task,
            "contestant": contestant,
            "repetition": repetition,
            "left": left_map[(task, contestant, repetition)],
            "right": right_map[(task, contestant, repetition)],
        }
        for task, contestant, repetition in excluded
    ]
    return {
        "schema_version": 1,
        "kind": "arena_results_paired_comparison",
        "purpose": (
            "demonstration"
            if "demonstration" in (left_data["purpose"], right_data["purpose"])
            else left_data["purpose"]
        ),
        "left": {
            "label": left_label,
            "purpose": left_data["purpose"],
            "result_sha256": left_report["result_sha256"],
            "protocol": {
                "harness_revision": left_data["protocol"]["harness_revision"],
                "environment_sha256": left_data["protocol"]["environment_sha256"],
                "sampling_sha256": left_data["protocol"]["sampling_sha256"],
            },
            "summary": {
                "independent_tasks": left_report["independent_tasks"],
                "matched_blocks": left_report["matched_blocks"],
                "planned_blocks": left_report["planned_blocks"],
                "excluded_blocks": left_report["excluded_blocks"],
                "contestants": {
                    name: {
                        "outcomes": _outcome_counts(row.get("outcomes")),
                        "matched_solved": row["matched_solved"],
                        "matched_attempts": row["matched_attempts"],
                        "matched_task_mean_solve_rate": row["matched_task_mean_solve_rate"],
                        "grade": row.get("grade"),
                    }
                    for name, row in left_report["contestants"].items()
                },
            },
        },
        "right": {
            "label": right_label,
            "purpose": right_data["purpose"],
            "result_sha256": right_report["result_sha256"],
            "protocol": {
                "harness_revision": right_data["protocol"]["harness_revision"],
                "environment_sha256": right_data["protocol"]["environment_sha256"],
                "sampling_sha256": right_data["protocol"]["sampling_sha256"],
            },
            "summary": {
                "independent_tasks": right_report["independent_tasks"],
                "matched_blocks": right_report["matched_blocks"],
                "planned_blocks": right_report["planned_blocks"],
                "excluded_blocks": right_report["excluded_blocks"],
                "contestants": {
                    name: {
                        "outcomes": _outcome_counts(row.get("outcomes")),
                        "matched_solved": row["matched_solved"],
                        "matched_attempts": row["matched_attempts"],
                        "matched_task_mean_solve_rate": row["matched_task_mean_solve_rate"],
                        "grade": row.get("grade"),
                    }
                    for name, row in right_report["contestants"].items()
                },
            },
        },
        "setup_differences": setup_differences,
        "warnings": warnings,
        "matched_attempts": len(matched),
        "excluded_infrastructure_attempts": infra,
        "one_side_only": {
            "left": [f"{t}/{c}#{r}" for t, c, r in left_only],
            "right": [f"{t}/{c}#{r}" for t, c, r in right_only],
        },
        "totals": {
            "left": left_totals,
            "right": right_totals,
            "solved_difference": right_totals["solved"] - left_totals["solved"],
        },
        "paired": {
            key: paired.get(key, 0)
            for key in ("both_solved", "left_only_solved", "right_only_solved", "neither_solved")
        },
        "changed_tasks": changed,
        "unchanged_tasks": len(tasks) - len(changed),
        "timeouts": timeouts,
    }


def _rows_or_empty(rows_html, empty_message):
    return rows_html if rows_html else f"<p class='empty'>{_esc(empty_message)}</p>"


def render_paired_compare_html(
    report,
    *,
    left_dashboard_href=None,
    right_dashboard_href=None,
    source_left="left",
    source_right="right",
):
    """Render paired-run compare HTML from an Arena or Keel Mobile compare report."""
    left = report["left"]
    right = report["right"]
    left_label = left["label"]
    right_label = right["label"]
    purpose = report.get("purpose") or "local comparison"
    if purpose.startswith("local comparison"):
        purpose_badge = "demonstration"
    else:
        purpose_badge = purpose
    purpose_class = _purpose_class(purpose_badge)
    left_purpose = left.get("purpose") or purpose_badge
    right_purpose = right.get("purpose") or purpose_badge

    warnings_html = ""
    if report.get("warnings"):
        items = "".join(f"<li>{_esc(item)}</li>" for item in report["warnings"])
        warnings_html = (
            f"<section class='panel'><h2>Warnings</h2>"
            f"<ul class='warnings'>{items}</ul></section>"
        )

    setup_rows = "".join(
        "<tr>"
        f"<td><code>{_esc(row['field'])}</code></td>"
        f"<td><code title='{_esc(row.get('left'))}'>{_esc(_short_digest(row.get('left'), 16) if row.get('left') is not None else '—')}</code></td>"
        f"<td><code title='{_esc(row.get('right'))}'>{_esc(_short_digest(row.get('right'), 16) if row.get('right') is not None else '—')}</code></td>"
        "</tr>"
        for row in report.get("setup_differences") or []
    )
    setup_block = _rows_or_empty(
        f"<table><thead><tr><th>Field</th><th>{_esc(left_label)}</th><th>{_esc(right_label)}</th></tr></thead>"
        f"<tbody>{setup_rows}</tbody></table>"
        if setup_rows
        else "",
        "No recorded protocol, digest, or setup differences.",
    )

    totals = report["totals"]
    left_total = totals["left"]
    right_total = totals["right"]
    paired = report.get("paired") or {}

    changed_rows = ""
    for entry in report.get("changed_tasks") or []:
        if "suite" in entry:
            samples = "; ".join(
                f"#{s['sample']} {s['left']} → {s['right']}" for s in entry["samples"]
            )
            changed_rows += (
                "<tr>"
                f"<td>{_esc(entry['suite'])}</td>"
                f"<td>{_esc(entry['task'])}</td>"
                f"<td class='num'>{entry['left_solved']}/{entry['attempts']}</td>"
                f"<td class='num'>{entry['right_solved']}/{entry['attempts']}</td>"
                f"<td class='num'>{entry['difference']:+d}</td>"
                f"<td>{_esc(samples)}</td>"
                "</tr>"
            )
        else:
            samples = "; ".join(
                f"#{s['repetition']} {s['left']} → {s['right']}" for s in entry["samples"]
            )
            changed_rows += (
                "<tr>"
                f"<td>{_esc(entry['contestant'])}</td>"
                f"<td>{_esc(entry['task'])}</td>"
                f"<td class='num'>{entry['left_solved']}/{entry['attempts']}</td>"
                f"<td class='num'>{entry['right_solved']}/{entry['attempts']}</td>"
                f"<td class='num'>{entry['difference']:+d}</td>"
                f"<td>{_esc(samples)}</td>"
                "</tr>"
            )
    changed_head = (
        f"<th>Suite</th><th>Task</th><th>{_esc(left_label)}</th><th>{_esc(right_label)}</th>"
        "<th>Diff</th><th>Samples</th>"
        if report.get("changed_tasks") and "suite" in report["changed_tasks"][0]
        else (
            f"<th>Contestant</th><th>Task</th><th>{_esc(left_label)}</th><th>{_esc(right_label)}</th>"
            "<th>Diff</th><th>Repetitions</th>"
        )
    )
    changed_block = _rows_or_empty(
        f"<table><thead><tr>{changed_head}</tr></thead><tbody>{changed_rows}</tbody></table>"
        if changed_rows
        else "",
        "No matched attempt changed outcome.",
    )

    timeout_rows = ""
    for entry in report.get("timeouts") or []:
        if "suite" in entry:
            timeout_rows += (
                "<tr>"
                f"<td>{_esc(entry['suite'])}</td>"
                f"<td>{_esc(entry['task'])}</td>"
                f"<td class='num'>{entry['sample']}</td>"
                f"<td class='warn'>{_esc(entry['left'])}</td>"
                f"<td class='warn'>{_esc(entry['right'])}</td>"
                "</tr>"
            )
        else:
            timeout_rows += (
                "<tr>"
                f"<td>{_esc(entry['contestant'])}</td>"
                f"<td>{_esc(entry['task'])}</td>"
                f"<td class='num'>{entry['repetition']}</td>"
                f"<td class='warn'>{_esc(entry['left'])}</td>"
                f"<td class='warn'>{_esc(entry['right'])}</td>"
                "</tr>"
            )
    timeout_head = (
        f"<th>Suite</th><th>Task</th><th>Sample</th><th>{_esc(left_label)}</th><th>{_esc(right_label)}</th>"
        if report.get("timeouts") and "suite" in report["timeouts"][0]
        else (
            f"<th>Contestant</th><th>Task</th><th>Rep</th><th>{_esc(left_label)}</th>"
            f"<th>{_esc(right_label)}</th>"
        )
    )
    timeout_block = _rows_or_empty(
        f"<table><thead><tr>{timeout_head}</tr></thead><tbody>{timeout_rows}</tbody></table>"
        if timeout_rows
        else "",
        "No matched attempt timed out.",
    )

    infra = report.get("excluded_infrastructure_attempts") or []
    infra_rows = ""
    for entry in infra:
        if "suite" in entry:
            label = f"{entry['suite']}/{entry['task']}#{entry['sample']}"
        else:
            label = f"{entry['contestant']}/{entry['task']}#{entry['repetition']}"
        infra_rows += (
            "<tr>"
            f"<td><code>{_esc(label)}</code></td>"
            f"<td class='infra'>{_esc(entry['left'])}</td>"
            f"<td class='infra'>{_esc(entry['right'])}</td>"
            "</tr>"
        )
    one = report.get("one_side_only") or {"left": [], "right": []}
    one_notes = []
    for side, name in (("left", left_label), ("right", right_label)):
        cells = one.get(side) or []
        if cells:
            preview = ", ".join(cells[:20])
            suffix = f" and {len(cells) - 20} more" if len(cells) > 20 else ""
            one_notes.append(f"recorded only in {name}: {preview}{suffix}")
    infra_block = ""
    if infra_rows or one_notes:
        infra_table = (
            f"<table><thead><tr><th>Cell</th><th>{_esc(left_label)}</th><th>{_esc(right_label)}</th></tr></thead>"
            f"<tbody>{infra_rows}</tbody></table>"
            if infra_rows
            else ""
        )
        notes = "".join(f"<li>{_esc(note)}</li>" for note in one_notes)
        infra_block = (
            "<section class='panel'><h2>Infra exclusions &amp; one-sided cells</h2>"
            f"{infra_table}"
            + (f"<ul class='warnings'>{notes}</ul>" if notes else "")
            + "</section>"
        )

    card_actions = []
    if left_dashboard_href:
        card_actions.append(
            f"<a class='button' href='{_esc(left_dashboard_href)}' target='_blank' rel='noopener'>"
            f"{_esc(left_label)} dashboard</a>"
        )
    if right_dashboard_href:
        card_actions.append(
            f"<a class='button secondary' href='{_esc(right_dashboard_href)}' target='_blank' rel='noopener'>"
            f"{_esc(right_label)} dashboard</a>"
        )
    cards_section = ""
    if card_actions:
        cards_section = (
            "<section class='panel'><h2>Per-run cards</h2>"
            f"<div class='actions'>{''.join(card_actions)}</div></section>"
        )

    kind = report.get("kind", "paired_comparison")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Keel Arena Paired Compare</title>
<style>{_shared_css()}</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Keel <span>Arena</span> Paired Compare</h1>
    <span class="badge {purpose_class}">{_esc(purpose_badge)}</span>
    <span class="badge {_purpose_class(left_purpose)}">{_esc(left_label)}: {_esc(left_purpose)}</span>
    <span class="badge {_purpose_class(right_purpose)}">{_esc(right_label)}: {_esc(right_purpose)}</span>
  </header>
  <p class="meta">
    Kind: <code>{_esc(kind)}</code> ·
    Left: <code>{_esc(source_left)}</code> ·
    Right: <code>{_esc(source_right)}</code> ·
    Matched attempts: {report.get('matched_attempts', 0)} ·
    Solved delta: <strong>{totals.get('solved_difference', 0):+d}</strong>
  </p>

  <section class="panel">
    <h2>Headline</h2>
    <p>
      <strong>{_esc(left_label)}</strong>
      {left_total.get('solved', 0)}/{left_total.get('attempts', 0)}
      ({_fmt_rate(left_total.get('solve_rate'))})
      →
      <strong>{_esc(right_label)}</strong>
      {right_total.get('solved', 0)}/{right_total.get('attempts', 0)}
      ({_fmt_rate(right_total.get('solve_rate'))})
    </p>
    <p class="note">
      Paired solved: both {paired.get('both_solved', 0)},
      only {_esc(left_label)} {paired.get('left_only_solved', 0)},
      only {_esc(right_label)} {paired.get('right_only_solved', 0)},
      neither {paired.get('neither_solved', 0)}.
      Unchanged tasks: {report.get('unchanged_tasks', 0)}.
    </p>
  </section>

  {warnings_html}

  <section class="panel">
    <h2>Provenance / setup diffs</h2>
    {setup_block}
    <p class="note">Pin digests before reading score deltas. Verifier bodies stay out of this view.</p>
  </section>

  <section class="panel">
    <h2>Changed tasks</h2>
    {changed_block}
  </section>

  <section class="panel">
    <h2>Timeouts</h2>
    {timeout_block}
  </section>

  {infra_block}
  {cards_section}
</div>
</body>
</html>
"""


def write_compare_bundle(results_path, out_dir, *, source_label=None):
    """Validate results, write compare index + cards under out_dir."""
    path = Path(results_path)
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    data = load(path)
    report = summarize(data)
    cards_dir = root / "cards"
    cards_meta = write_cards(report, cards_dir)
    label = source_label if source_label is not None else path.name
    index = render_compare_html(
        data,
        report,
        dashboard_href="cards/dashboard.html",
        source_label=label,
    )
    index_path = root / "index.html"
    index_path.write_text(index, encoding="utf-8")
    manifest = {
        "kind": "arena_single_compare",
        "purpose": report["purpose"],
        "result_sha256": report["result_sha256"],
        "index": str(index_path),
        "dashboard": str(cards_dir / "dashboard.html"),
        "cards": cards_meta,
        "independent_tasks": report["independent_tasks"],
        "matched_blocks": report["matched_blocks"],
        "planned_blocks": report["planned_blocks"],
        "excluded_blocks": report["excluded_blocks"],
        "contestants": {
            name: {
                "outcomes": _outcome_counts(row.get("outcomes")),
                "matched_solved": row["matched_solved"],
                "matched_attempts": row["matched_attempts"],
                "matched_task_mean_solve_rate": row["matched_task_mean_solve_rate"],
                "grade": row.get("grade"),
            }
            for name, row in report["contestants"].items()
        },
        "protocol": {
            "harness_revision": data["protocol"]["harness_revision"],
            "environment_sha256": data["protocol"]["environment_sha256"],
            "sampling_sha256": data["protocol"]["sampling_sha256"],
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def write_paired_compare_bundle(
    left_path,
    right_path,
    out_dir,
    *,
    left_label=None,
    right_label=None,
    left_setup=None,
    right_setup=None,
    suites=None,
):
    """Write a paired compare bundle for two Arena results or Keel Mobile runs."""
    left = Path(left_path)
    right = Path(right_path)
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    left_kind = detect_run_kind(left)
    right_kind = detect_run_kind(right)
    require(
        left_kind == right_kind,
        "paired compare requires matching artifact kinds (both results JSON or both Keel Mobile runs)",
    )

    left_dashboard = right_dashboard = None
    if left_kind == "arena_results":
        left_data = load(left)
        right_data = load(right)
        report = compare_arena_results(
            left_data,
            right_data,
            left_label=left_label or left.name,
            right_label=right_label or right.name,
        )
        left_cards = write_cards(summarize(left_data), root / "left" / "cards")
        right_cards = write_cards(summarize(right_data), root / "right" / "cards")
        left_dashboard = "left/cards/dashboard.html"
        right_dashboard = "right/cards/dashboard.html"
        (root / "paired.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        cards_meta = {"left": left_cards, "right": right_cards}
    else:
        left_run = load_run(left, parse_setup_pairs(left_setup), left_label)
        right_run = load_run(right, parse_setup_pairs(right_setup), right_label)
        if left_run["label"] == right_run["label"]:
            left_run["label"] = left_run["label"] + " (left)"
            right_run["label"] = right_run["label"] + " (right)"
        suite_list = None
        if suites:
            suite_list = [s.strip() for s in suites.split(",") if s.strip()]
        report = compare_runs(left_run, right_run, suites=suite_list)
        (root / "paired.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        cards_meta = None

    index = render_paired_compare_html(
        report,
        left_dashboard_href=left_dashboard,
        right_dashboard_href=right_dashboard,
        source_left=str(left),
        source_right=str(right),
    )
    index_path = root / "index.html"
    index_path.write_text(index, encoding="utf-8")
    manifest = {
        "kind": report["kind"],
        "purpose": report["purpose"],
        "artifact_kind": left_kind,
        "index": str(index_path),
        "paired": str(root / "paired.json"),
        "left_label": report["left"]["label"],
        "right_label": report["right"]["label"],
        "matched_attempts": report.get("matched_attempts"),
        "solved_difference": report["totals"]["solved_difference"],
        "changed_tasks": len(report.get("changed_tasks") or []),
        "timeouts": len(report.get("timeouts") or []),
        "excluded_infrastructure_attempts": len(
            report.get("excluded_infrastructure_attempts") or []
        ),
        "setup_differences": len(report.get("setup_differences") or []),
        "warnings": report.get("warnings") or [],
        "cards": cards_meta,
        "left_dashboard": str(root / left_dashboard) if left_dashboard else None,
        "right_dashboard": str(root / right_dashboard) if right_dashboard else None,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def serve_compare_bundle(out_dir, *, port=0, open_browser=True, ready=None):
    """Serve out_dir on loopback. Returns (server, url, thread).

    Call server.shutdown() to stop. When ready is a threading.Event, it is set
    after the server starts accepting connections.
    """
    root = Path(out_dir).resolve()
    listen_port = port if port else _free_port()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, format, *args):  # noqa: A003 — stdlib signature
            return

    server = ThreadingHTTPServer(("127.0.0.1", listen_port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"

    def _serve():
        try:
            server.serve_forever(poll_interval=0.1)
        finally:
            server.server_close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    if ready is not None:
        ready.set()
    if open_browser:
        webbrowser.open(url)
    return server, url, thread
