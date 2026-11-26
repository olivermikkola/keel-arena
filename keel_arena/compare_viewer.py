"""Offline local compare shell: load results, summarize, write cards, serve HTML.

Wraps validate/report/cards library APIs. No model calls, no orchestration engine,
no network egress beyond an optional loopback HTTP server for viewing.
"""

from __future__ import annotations

import html
import json
import socket
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .cards import write_cards
from .results import load, summarize

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


def render_compare_html(data, report, *, dashboard_href="cards/dashboard.html", source_label="results.json"):
    """Render a single-page compare shell from validated results + summarize()."""
    protocol = data["protocol"]
    purpose = report["purpose"]
    purpose_class = "badge-demo" if purpose == "demonstration" else "badge-bench"
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
<style>
:root {{
  --bg: #0a1112;
  --panel: #101a1c;
  --line: #22363a;
  --text: #eef4f2;
  --muted: #8ca3a0;
  --teal: #36b394;
  --coral: #dc7648;
  --cream: #f7f3e9;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  padding: 24px;
  background: radial-gradient(1200px 600px at 10% -10%, #143038 0%, var(--bg) 55%);
  color: var(--text);
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
  line-height: 1.45;
}}
.wrap {{ max-width: 980px; margin: 0 auto; }}
header {{ display: flex; flex-wrap: wrap; gap: 12px 18px; align-items: baseline; margin-bottom: 18px; }}
h1 {{ margin: 0; font-size: 1.6rem; color: var(--cream); letter-spacing: 0.02em; }}
h1 span {{ color: var(--teal); }}
.badge {{
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}}
.badge-demo {{ background: #3a2a18; color: #f0c48a; border: 1px solid #6a4a22; }}
.badge-bench {{ background: #12332c; color: #8fe0c8; border: 1px solid #2a6a58; }}
.meta {{ color: var(--muted); font-size: 0.92rem; margin-bottom: 18px; }}
.panel {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 16px;
  margin: 14px 0;
}}
h2 {{ margin: 0 0 12px; font-size: 1.05rem; color: var(--cream); }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
th, td {{ padding: 8px 10px; border-bottom: 1px solid #1a2b2e; text-align: left; }}
th {{ color: var(--muted); font-weight: 600; }}
td.ok {{ color: var(--teal); font-variant-numeric: tabular-nums; }}
td.warn {{ color: #e5a95e; font-variant-numeric: tabular-nums; }}
td.infra {{ color: var(--coral); font-variant-numeric: tabular-nums; }}
code {{ font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 0.85rem; }}
.actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; }}
a.button {{
  display: inline-block;
  padding: 10px 14px;
  background: var(--teal);
  color: #041210;
  text-decoration: none;
  border-radius: 8px;
  font-weight: 700;
}}
a.button.secondary {{ background: transparent; color: var(--text); border: 1px solid var(--line); }}
.note {{ color: var(--muted); font-size: 0.85rem; margin-top: 10px; }}
</style>
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
