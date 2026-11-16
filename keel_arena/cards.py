"""Shareable SVG scorecards and offline HTML Arena dashboard (stdlib only)."""

import html
from pathlib import Path

SUITE_LABELS = {
    "coding": "CODING",
    "tool-use": "TOOL USE",
    "adversarial": "ADVERSARIAL",
    "agent-chains": "AGENT CHAINS",
    "structured": "STRUCTURED",
    "retrieval": "RETRIEVAL",
    "instruction": "INSTRUCTION",
    "repair": "REPAIR",
    "uncategorized": "GENERAL",
}


def _esc(value):
    return html.escape(str(value), quote=True)


def _trunc(text, max_len=28):
    s = str(text)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _grade_color(rate):
    if rate is None:
        return "#94a3b8"
    if rate >= 0.85:
        return "#4ade80"
    if rate >= 0.70:
        return "#facc15"
    if rate >= 0.50:
        return "#fb923c"
    return "#f87171"


def _ranked_contestants(report):
    return sorted(
        report["contestants"].items(),
        key=lambda item: (
            -(item[1]["matched_task_mean_solve_rate"] if item[1]["matched_task_mean_solve_rate"] is not None else -1.0),
            -(item[1]["matched_solve_rate"] if item[1]["matched_solve_rate"] is not None else -1.0),
            item[0],
        ),
    )


def _fmt_rate(val):
    return "N/A" if val is None else f"{val * 100:.1f}%"


def _fmt_tok(val):
    if val is None:
        return "unknown"
    if val >= 1000:
        return f"{round(val / 1000)}K tok"
    return f"{val} tok"


def _judge_summary_label(report):
    gs = report.get("grading_summary") or {}
    modes = gs.get("modes") or {}
    cal = gs.get("calibration")
    if cal:
        return f"Frontier LLM + Human Calibrated ({cal.get('judge_human_agreement_rate', 0) * 100:.0f}% agree)"
    if "llm_judge" in modes and "deterministic" in modes:
        return "Hybrid (Deterministic + Frontier LLM Judge)"
    if "hybrid" in modes:
        return "Hybrid (Deterministic + Frontier LLM Judge)"
    if "llm_judge" in modes:
        return "Frontier LLM Judge"
    return "Deterministic Verifiers"


def render_overview_svg(report):
    """Render an SLM-Gauntlet-inspired Arena overview SVG card."""
    ranked = _ranked_contestants(report)
    suites = list((report.get("per_suite") or {}).items())
    suite_rows = max(1, (len(suites) + 3) // 4)
    contestant_count = min(len(ranked), 10)
    height = 360 + suite_rows * 76 + contestant_count * 64 + 130
    width = 860

    hw = report.get("hardware") or {}
    device_label = hw.get("device_label")
    if not device_label:
        for _, row in ranked:
            ep = row.get("edge_profile") or {}
            if ep.get("device"):
                device_label = ep["device"]
                break
    device_label = device_label or "Local / Harbor Sandbox"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs>',
        '  <linearGradient id="topbar" x1="0%" y1="0%" x2="100%" y2="0%">',
        '    <stop offset="0%" stop-color="#38bdf8"/>',
        '    <stop offset="50%" stop-color="#facc15"/>',
        '    <stop offset="100%" stop-color="#f472b6"/>',
        '  </linearGradient>',
        '  <style>',
        '    .bg { fill: #0b0f17; }',
        '    .panel { fill: #131926; stroke: #242f45; stroke-width: 1.5; }',
        '    .muted { fill: #94a3b8; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }',
        '    .title { fill: #f8fafc; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; font-weight: 800; }',
        '    .mono { fill: #cbd5e1; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }',
        '  </style>',
        '</defs>',
        f'<rect width="{width}" height="{height}" rx="18" class="bg"/>',
        f'<rect x="0" y="0" width="{width}" height="5" fill="url(#topbar)"/>',
        '<text x="40" y="46" font-size="13" letter-spacing="2" class="muted">KEEL ARENA · EDGE AGENTIC BENCHMARK · '
        f'{_esc(report["purpose"].upper())} · {len(ranked)} CONTESTANTS</text>',
        '<text x="40" y="92" font-size="40" class="title">Keel <tspan fill="#facc15">Arena</tspan></text>',
        f'<text x="40" y="124" font-size="16" class="muted">Matched tasks: {report["tasks_with_matched_attempts"]}/{report["independent_tasks"]} · '
        f'Matched blocks: {report["matched_blocks"]}/{report["planned_blocks"]} · {_esc(_judge_summary_label(report))}</text>',
    ]

    # Suite cards
    y = 152
    col_w = 186
    gap = 12
    for idx, (suite, sdata) in enumerate(suites):
        col = idx % 4
        row = idx // 4
        sx = 40 + col * (col_w + gap)
        sy = y + row * 76
        label = SUITE_LABELS.get(suite, suite.upper())
        parts.append(f'<rect x="{sx}" y="{sy}" width="{col_w}" height="64" rx="10" class="panel"/>')
        parts.append(f'<text x="{sx + col_w / 2}" y="{sy + 24}" text-anchor="middle" font-size="11" letter-spacing="1.2" class="muted">{_esc(label)}</text>')
        parts.append(f'<text x="{sx + col_w / 2}" y="{sy + 48}" text-anchor="middle" font-size="22" class="title">{sdata["tasks"]} <tspan font-size="13" font-weight="400" fill="#94a3b8">tasks</tspan></text>')

    y = y + suite_rows * 76 + 22
    parts.append(f'<text x="40" y="{y}" font-size="12" letter-spacing="1.6" class="muted">LEADERBOARD · TASK-MEAN SOLVE RATE · GRADE</text>')
    y += 18

    for rank, (name, row) in enumerate(ranked[:contestant_count], 1):
        rate = row.get("matched_task_mean_solve_rate")
        color = _grade_color(rate)
        bar_w = int((rate or 0.0) * 210)
        harness = row.get("harness") or "keel"
        quant = row.get("quantization") or "unknown"
        ep = row.get("edge_profile") or {}
        tok_s = row.get("mean_decode_tok_s") or ep.get("speed_1_stream_tok_s")
        speed_txt = f"{tok_s:.1f} tok/s" if tok_s is not None else "speed unknown"
        parts.append(f'<rect x="40" y="{y}" width="780" height="54" rx="10" class="panel"/>')
        parts.append(f'<circle cx="70" cy="{y + 27}" r="14" fill="#1e293b" stroke="{color}" stroke-width="2"/>')
        parts.append(f'<text x="70" y="{y + 32}" text-anchor="middle" font-size="13" class="title">{rank}</text>')
        parts.append(f'<text x="100" y="{y + 25}" font-size="17" class="title">{_esc(_trunc(name, 26))}</text>')
        parts.append(f'<text x="100" y="{y + 43}" font-size="12" class="muted">{_esc(quant)} · {_esc(harness)} · {_esc(speed_txt)}</text>')
        parts.append(f'<rect x="440" y="{y + 22}" width="210" height="10" rx="5" fill="#1e293b"/>')
        parts.append(f'<rect x="440" y="{y + 22}" width="{bar_w}" height="10" rx="5" fill="{color}"/>')
        parts.append(f'<text x="735" y="{y + 33}" text-anchor="end" font-size="20" font-weight="800" fill="{color}" font-family="ui-sans-serif, system-ui, sans-serif">{_fmt_rate(rate)}</text>')
        parts.append(f'<text x="795" y="{y + 33}" text-anchor="end" font-size="16" font-weight="800" fill="{color}" font-family="ui-sans-serif, system-ui, sans-serif">{_esc(row.get("grade", "N/A"))}</text>')
        y += 64

    y += 14
    box_w = 252
    footer_cards = [
        ("GRADING", _trunc(_judge_summary_label(report), 30), "Reproducible & audit-hashed"),
        ("HARDWARE", _trunc(device_label, 28), "Auto-detected / pinned profile"),
        ("PROVENANCE", f"sha256:{report['result_sha256'][:12]}", f"Schema v{report['schema_version']} · matched matrix"),
    ]
    for i, (k, v, sub) in enumerate(footer_cards):
        bx = 40 + i * (box_w + 12)
        parts.append(f'<rect x="{bx}" y="{y}" width="{box_w}" height="74" rx="10" class="panel"/>')
        parts.append(f'<text x="{bx + 14}" y="{y + 20}" font-size="11" letter-spacing="1.2" class="muted">{_esc(k)}</text>')
        parts.append(f'<text x="{bx + 14}" y="{y + 44}" font-size="14" class="title">{_esc(v)}</text>')
        parts.append(f'<text x="{bx + 14}" y="{y + 62}" font-size="11" class="muted">{_esc(sub)}</text>')

    parts.append('</svg>')
    return "\n".join(parts)


def render_contestant_card_svg(report, contestant_name):
    """Render an SLM-Gauntlet-style trading-card SVG for one contestant."""
    if contestant_name not in report["contestants"]:
        raise KeyError(f"unknown contestant: {contestant_name}")
    ranked = _ranked_contestants(report)
    rank = next(i for i, (n, _) in enumerate(ranked, 1) if n == contestant_name)
    row = report["contestants"][contestant_name]
    ep = row.get("edge_profile") or {}
    hw = report.get("hardware") or {}
    rate = row.get("matched_task_mean_solve_rate")
    color = _grade_color(rate)
    grade = row.get("grade", "N/A")
    harness = row.get("harness") or "keel"
    quant = row.get("quantization") or "unknown"

    suites = list((report.get("per_suite") or {}).items())
    suite_rows = max(1, (len(suites) + 3) // 4)
    width = 800
    height = 385 + suite_rows * 78 + 250

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs>',
        '  <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="0%">',
        '    <stop offset="0%" stop-color="#34d399"/>',
        '    <stop offset="50%" stop-color="#facc15"/>',
        '    <stop offset="100%" stop-color="#f472b6"/>',
        '  </linearGradient>',
        '  <style>',
        '    .bg { fill: #0b0f17; }',
        '    .tile { fill: #131926; stroke: #242f45; stroke-width: 1.5; }',
        '    .muted { fill: #94a3b8; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }',
        '    .title { fill: #f8fafc; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; font-weight: 800; }',
        '  </style>',
        '</defs>',
        f'<rect width="{width}" height="{height}" rx="18" class="bg"/>',
        f'<rect x="0" y="0" width="{width}" height="5" fill="url(#accent)"/>',
        f'<text x="36" y="54" font-size="34" class="title">{_esc(_trunc(contestant_name, 26))}</text>',
        f'<text x="36" y="80" font-size="15" class="muted">{_esc(quant)} · harness: {_esc(harness)}</text>',
        f'<text x="640" y="64" text-anchor="end" font-size="22" class="muted">#{rank}</text>',
        f'<text x="720" y="72" text-anchor="middle" font-size="52" font-weight="900" fill="{color}" font-family="ui-sans-serif, system-ui, sans-serif">{_esc(grade)}</text>',
        f'<text x="720" y="94" text-anchor="middle" font-size="11" letter-spacing="1.4" fill="{color}" font-family="ui-sans-serif, system-ui, sans-serif">AGENTIC GRADE</text>',
        f'<text x="36" y="156" font-size="58" font-weight="900" fill="{color}" font-family="ui-sans-serif, system-ui, sans-serif">{_fmt_rate(rate)}</text>',
        f'<text x="36" y="182" font-size="13" letter-spacing="1.4" class="muted">ARENA SCORE · {row["matched_solved"]}/{row["matched_attempts"]} SOLVED · {len(suites)} SUITES</text>',
    ]

    # Suite breakdown tiles
    y = 204
    tile_w = 172
    gap = 12
    for idx, (suite, sdata) in enumerate(suites):
        col = idx % 4
        r = idx // 4
        tx = 36 + col * (tile_w + gap)
        ty = y + r * 78
        s_rate = sdata["contestants"][contestant_name]["task_mean_solve_rate"]
        s_col = _grade_color(s_rate)
        bar_w = int((s_rate or 0.0) * (tile_w - 28))
        label = SUITE_LABELS.get(suite, suite.upper())
        parts.append(f'<rect x="{tx}" y="{ty}" width="{tile_w}" height="66" rx="8" class="tile"/>')
        parts.append(f'<text x="{tx + tile_w / 2}" y="{ty + 21}" text-anchor="middle" font-size="11" letter-spacing="1" class="muted">{_esc(label)}</text>')
        parts.append(f'<text x="{tx + tile_w / 2}" y="{ty + 46}" text-anchor="middle" font-size="22" font-weight="800" fill="{s_col}" font-family="ui-sans-serif, system-ui, sans-serif">{_fmt_rate(s_rate)}</text>')
        parts.append(f'<rect x="{tx + 14}" y="{ty + 54}" width="{tile_w - 28}" height="5" rx="2.5" fill="#1e293b"/>')
        parts.append(f'<rect x="{tx + 14}" y="{ty + 54}" width="{bar_w}" height="5" rx="2.5" fill="{s_col}"/>')

    # 9-tile Edge telemetry grid
    y = y + suite_rows * 78 + 14
    s1 = row.get("mean_decode_tok_s") or ep.get("speed_1_stream_tok_s")
    sn = ep.get("speed_n_streams_tok_s")
    if s1 is not None and sn is not None:
        speed_val = f"{s1:.0f} → {sn:.0f} tok/s"
    elif s1 is not None:
        speed_val = f"{s1:.1f} tok/s"
    else:
        speed_val = "unknown"
    ttft = row.get("median_ttft_seconds") or ep.get("ttft_seconds")
    ttft_val = f"{ttft:.2f} s" if ttft is not None else "unknown"
    weights_val = f"{ep['weights_vram_gb']:.1f} GB" if ep.get("weights_vram_gb") is not None else "unknown"
    kv_pool_val = _fmt_tok(ep.get("kv_pool_tokens"))
    max_ctx_val = _fmt_tok(ep.get("max_context_tokens"))
    tps = row.get("tokens_per_solve")
    tps_val = f"{tps:,.0f}" if tps is not None else "unknown"
    kv_tok_val = f"{ep['kv_per_token_kb']:.1f} KB" if ep.get("kv_per_token_kb") is not None else "unknown"
    device_val = _trunc(ep.get("device") or hw.get("device_label") or "unknown", 22)
    offload_val = _trunc(ep.get("offload") or "unknown", 22)

    telemetry = [
        ("SPEED 1→N STREAMS", speed_val),
        ("TTFT", ttft_val),
        ("WEIGHTS MEM", weights_val),
        ("KV POOL", kv_pool_val),
        ("MAX CONTEXT", max_ctx_val),
        ("TOKENS / SOLVE", tps_val),
        ("KV PER TOKEN", kv_tok_val),
        ("DEVICE", device_val),
        ("OFFLOAD", offload_val),
    ]
    t_w = 234
    for idx, (k, v) in enumerate(telemetry):
        col = idx % 3
        r = idx // 3
        tx = 36 + col * (t_w + 13)
        ty = y + r * 66
        parts.append(f'<rect x="{tx}" y="{ty}" width="{t_w}" height="56" rx="8" class="tile"/>')
        parts.append(f'<text x="{tx + 12}" y="{ty + 20}" font-size="10" letter-spacing="1" class="muted">{_esc(k)}</text>')
        parts.append(f'<text x="{tx + 12}" y="{ty + 43}" font-size="16" class="title">{_esc(v)}</text>')

    y += 3 * 66 + 14
    diag = ep.get("diagnostic_note")
    if not diag and suites:
        scored = [
            (s, sdata["contestants"][contestant_name]["task_mean_solve_rate"])
            for s, sdata in suites
            if sdata["contestants"][contestant_name]["task_mean_solve_rate"] is not None
        ]
        if scored:
            best = max(scored, key=lambda x: x[1])
            worst = min(scored, key=lambda x: x[1])
            diag = (f"Strongest: {SUITE_LABELS.get(best[0], best[0])} ({_fmt_rate(best[1])}); "
                    f"weakest: {SUITE_LABELS.get(worst[0], worst[0])} ({_fmt_rate(worst[1])}).")
    diag = diag or f"Matched {row['matched_solved']}/{row['matched_attempts']} attempts across {report['independent_tasks']} tasks."
    parts.append(f'<line x1="38" y1="{y}" x2="38" y2="{y + 28}" stroke="#facc15" stroke-width="3"/>')
    parts.append(f'<text x="50" y="{y + 19}" font-size="13" class="muted">{_esc(_trunc(diag, 88))}</text>')
    parts.append(f'<text x="36" y="{height - 20}" font-size="11" class="muted">keel-arena v{report["schema_version"]} · '
                 f'{_esc(_judge_summary_label(report))} · sha256:{report["result_sha256"][:12]}</text>')
    parts.append('</svg>')
    return "\n".join(parts)


def render_dashboard_html(report):
    """Render a self-contained offline HTML5 + inline SVG Arena dashboard."""
    ranked = _ranked_contestants(report)
    suites = list((report.get("per_suite") or {}).items())
    elo = report.get("elo_ratings") or {}

    # Pareto scatter plot (Decode tok/s vs Task-mean solve rate)
    pts = []
    for name, row in ranked:
        ep = row.get("edge_profile") or {}
        spd = row.get("mean_decode_tok_s") or ep.get("speed_1_stream_tok_s")
        acc = row.get("matched_task_mean_solve_rate")
        if spd is not None and acc is not None:
            pts.append((name, spd, acc * 100.0, row.get("grade", "N/A")))
    pareto_svg = ""
    if pts:
        max_spd = max(p[1] for p in pts) * 1.15 or 10.0
        dots = []
        for name, spd, acc, _ in pts:
            cx = 55 + (spd / max_spd) * 410
            cy = 205 - (acc / 100.0) * 165
            col = _grade_color(acc / 100.0)
            dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{col}"/>')
            dots.append(f'<text x="{cx + 9:.1f}" y="{cy + 4:.1f}" font-size="11" fill="#e2e8f0">{_esc(_trunc(name, 18))}</text>')
        pareto_svg = (
            '<svg viewBox="0 0 540 240" width="100%" style="max-width:540px;background:#0f172a;border-radius:10px;border:1px solid #242f45">'
            '<line x1="55" y1="205" x2="495" y2="205" stroke="#334155"/>'
            '<line x1="55" y1="30" x2="55" y2="205" stroke="#334155"/>'
            '<text x="275" y="230" text-anchor="middle" font-size="11" fill="#94a3b8">Decode Speed (tok/s)</text>'
            '<text x="16" y="120" text-anchor="middle" font-size="11" fill="#94a3b8" transform="rotate(-90 16 120)">Accuracy (%)</text>'
            + "".join(dots)
            + "</svg>"
        )

    # Leaderboard rows
    lb_rows = []
    for rank, (name, row) in enumerate(ranked, 1):
        ep = row.get("edge_profile") or {}
        spd = row.get("mean_decode_tok_s") or ep.get("speed_1_stream_tok_s")
        ttft = row.get("median_ttft_seconds") or ep.get("ttft_seconds")
        tps = row.get("tokens_per_solve")
        elo_val = f"{elo[name]['elo']:.0f}" if name in elo else "—"
        lb_rows.append(
            f"<tr><td>#{rank}</td><td><strong>{_esc(name)}</strong></td>"
            f"<td>{_esc(row.get('harness') or 'keel')}</td>"
            f"<td>{_esc(row.get('quantization') or 'unknown')}</td>"
            f"<td style='color:{_grade_color(row.get('matched_task_mean_solve_rate'))};font-weight:700'>{_esc(row.get('grade', 'N/A'))}</td>"
            f"<td>{_fmt_rate(row.get('matched_task_mean_solve_rate'))}</td>"
            f"<td>{row['matched_solved']}/{row['matched_attempts']}</td>"
            f"<td>{elo_val}</td>"
            f"<td>{f'{spd:.1f}' if spd is not None else 'unknown'}</td>"
            f"<td>{f'{ttft:.2f}s' if ttft is not None else 'unknown'}</td>"
            f"<td>{f'{tps:,.0f}' if tps is not None else 'unknown'}</td></tr>"
        )

    # Multi-panel suite grid (Qwen 4 benchmark grid style!)
    suite_panels = []
    for suite, sdata in suites:
        bars = []
        for name, _ in ranked[:6]:
            srate = sdata["contestants"][name]["task_mean_solve_rate"]
            pct = (srate or 0.0) * 100.0
            col = _grade_color(srate)
            bars.append(
                f"<div class='bar-row'><span class='bar-lbl'>{_esc(_trunc(name, 16))}</span>"
                f"<div class='bar-track'><div class='bar-fill' style='width:{pct:.1f}%;background:{col}'></div></div>"
                f"<span class='bar-val'>{_fmt_rate(srate)}</span></div>"
            )
        suite_panels.append(
            f"<div class='card'><h3>{_esc(SUITE_LABELS.get(suite, suite.upper()))} <span>({sdata['tasks']} tasks)</span></h3>"
            + "".join(bars)
            + "</div>"
        )

    # Per-task matrix
    task_headers = "".join(f"<th>{_esc(n)}</th>" for n, _ in ranked)
    task_rows = []
    for task, tdata in report["per_task"].items():
        cells = []
        n = len(tdata["matched_repetitions"])
        for name, _ in ranked:
            c = tdata["contestants"][name]
            cells.append(f"<td>{c['solved']}/{n} ({_fmt_rate(c['solve_rate'])})</td>" if n else "<td>unknown</td>")
        task_rows.append(
            f"<tr><td>{_esc(task)}</td><td>{_esc(tdata.get('suite') or '—')}</td>"
            f"<td>{_esc(tdata.get('judge_mode', 'deterministic'))}</td>{''.join(cells)}</tr>"
        )

    cal = (report.get("grading_summary") or {}).get("calibration")
    cal_html = ""
    if cal:
        cal_html = (
            f"<div class='card'><h3>Human Calibration Audit</h3>"
            f"<p>Reviewed: <strong>{cal['reviewed_count']}</strong> · Overrides: <strong>{cal['override_count']}</strong> · "
            f"Judge-Human Agreement: <strong>{cal['judge_human_agreement_rate'] * 100:.1f}%</strong> · "
            f"Cohen's κ: <strong>{cal.get('cohens_kappa', 'N/A')}</strong></p></div>"
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Keel Arena Report</title>
<style>
body{{margin:0;padding:24px;background:#0b0f17;color:#e2e8f0;font-family:ui-sans-serif,system-ui,-apple-system,sans-serif}}
.wrap{{max-width:1160px;margin:0 auto}}
h1,h2,h3{{margin:0 0 12px;color:#f8fafc}}
.meta{{color:#94a3b8;margin-bottom:20px;font-size:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin:18px 0}}
.card{{background:#131926;border:1px solid #242f45;border-radius:12px;padding:16px}}
.card h3 span{{color:#94a3b8;font-size:12px;font-weight:400}}
table{{width:100%;border-collapse:collapse;background:#131926;border:1px solid #242f45;border-radius:10px;overflow:hidden;margin:14px 0}}
th,td{{padding:10px 12px;border-bottom:1px solid #1e293b;text-align:left;font-size:13px}}
th{{background:#0f172a;color:#94a3b8;font-weight:600}}
.bar-row{{display:flex;align-items:center;gap:8px;margin:6px 0;font-size:12px}}
.bar-lbl{{width:110px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#cbd5e1}}
.bar-track{{flex:1;height:8px;background:#1e293b;border-radius:4px;overflow:hidden}}
.bar-fill{{height:100%;border-radius:4px}}
.bar-val{{width:48px;text-align:right;font-variant-numeric:tabular-nums}}
</style></head><body><div class="wrap">
<h1>Keel <span style="color:#facc15">Arena</span></h1>
<div class="meta">Purpose: <strong>{_esc(report['purpose'])}</strong> · Tasks: {report['independent_tasks']} ·
Matched blocks: {report['matched_blocks']}/{report['planned_blocks']} · Judge: {_esc(_judge_summary_label(report))} ·
<code>sha256:{report['result_sha256'][:12]}</code></div>
<h2>Leaderboard</h2>
<table><thead><tr><th>Rank</th><th>Contestant</th><th>Harness</th><th>Quant</th><th>Grade</th><th>Task Mean</th><th>Solved</th><th>Elo</th><th>Decode tok/s</th><th>Median TTFT</th><th>Tokens/Solve</th></tr></thead>
<tbody>{''.join(lb_rows)}</tbody></table>
{cal_html}
<h2>Suite Breakdown</h2>
<div class="grid">{''.join(suite_panels)}</div>
{('<h2>Speed vs Accuracy</h2>' + pareto_svg) if pareto_svg else ''}
<h2>Per-Task Breakdown</h2>
<table><thead><tr><th>Task</th><th>Suite</th><th>Judge</th>{task_headers}</tr></thead>
<tbody>{''.join(task_rows)}</tbody></table>
</div></body></html>
"""


def write_cards(report, out_dir):
    """Write overview.svg, per-contestant SVG cards, and dashboard.html into out_dir."""
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    written = []
    overview_path = root / "overview.svg"
    overview_path.write_text(render_overview_svg(report) + "\n", encoding="utf-8")
    written.append(str(overview_path))
    for name in sorted(report["contestants"]):
        card_path = root / f"card-{name}.svg"
        card_path.write_text(render_contestant_card_svg(report, name) + "\n", encoding="utf-8")
        written.append(str(card_path))
    dash_path = root / "dashboard.html"
    dash_path.write_text(render_dashboard_html(report), encoding="utf-8")
    written.append(str(dash_path))
    return {"written": written, "cards": len(report["contestants"]) + 1}
