"""Readable local reports; never uploads or chooses a winning model."""


def _rate(value):
    return 'unknown' if value is None else f'{value:.1%}'


def _num(value, fmt='.1f'):
    return 'unknown' if value is None else format(value, fmt)


def markdown(report):
    names = sorted(report['contestants'])
    lines = ['# Keel Arena', '', f"Purpose: **{report['purpose']}**", '',
             f"Tasks: {report['independent_tasks']}; matched blocks: {report['matched_blocks']}/{report['planned_blocks']}; "
             f"excluded blocks: {report['excluded_blocks']}.", '',
             '| Contestant | Solved / matched attempts | Task mean | Input tokens | Output tokens | Total wall seconds |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name in names:
        row = report['contestants'][name]
        def known(key):
            return 'unknown' if row[key] is None else str(row[key])
        lines.append(f"| {name} | {row['matched_solved']} / {row['matched_attempts']} | "
                     f"{_rate(row['matched_task_mean_solve_rate'])} | {known('matched_input_tokens')} | "
                     f"{known('matched_output_tokens')} | {row['matched_wall_seconds']:.1f} |")

    per_suite = report.get('per_suite') or {}
    if any(suite != 'uncategorized' for suite in per_suite):
        lines += ['', '## Suites', '',
                  '| Suite | Tasks | ' + ' | '.join(names) + ' |',
                  '| --- | ---: | ' + ' | '.join('---:' for _ in names) + ' |']
        for suite, row in per_suite.items():
            lines.append(f"| {suite} | {row['tasks']} | " +
                         ' | '.join(_rate(row['contestants'][n]['task_mean_solve_rate']) for n in names) + ' |')

    has_edge = any(
        row.get('median_ttft_seconds') is not None
        or row.get('mean_decode_tok_s') is not None
        or row.get('tokens_per_solve') is not None
        or row.get('edge_profile') is not None
        for row in report['contestants'].values()
    )
    if has_edge:
        lines += ['', '## Edge telemetry', '',
                  '| Contestant | Grade | Harness | Quant | Decode tok/s | Median TTFT (s) | Tokens / solve |',
                  '| --- | :---: | --- | --- | ---: | ---: | ---: |']
        for name in names:
            row = report['contestants'][name]
            ep = row.get('edge_profile') or {}
            tok_s = row.get('mean_decode_tok_s')
            if tok_s is None:
                tok_s = ep.get('speed_1_stream_tok_s')
            ttft = row.get('median_ttft_seconds')
            if ttft is None:
                ttft = ep.get('ttft_seconds')
            tps = row.get('tokens_per_solve')
            lines.append(
                f"| {name} | {row.get('grade', 'N/A')} | {row.get('harness') or 'keel'} | "
                f"{row.get('quantization') or 'unknown'} | {_num(tok_s)} | {_num(ttft, '.2f')} | "
                f"{'unknown' if tps is None else f'{tps:.0f}'} |"
            )

    elo = report.get('elo_ratings')
    if elo:
        lines += ['', '## Pairwise Arena Elo', '',
                  '| Contestant | Elo | W-L-T | Position consistency |',
                  '| --- | ---: | ---: | ---: |']
        for name, row in elo.items():
            lines.append(
                f"| {name} | {row['elo']:.1f} | {row['wins']}-{row['losses']}-{row['ties']} | "
                f"{_rate(row['position_consistency'])} |"
            )

    lines += ['', '## Repeated attempts', '',
              '| k | Eligible tasks | ' + ' | '.join(names) + ' |',
              '| ---: | ---: | ' + ' | '.join('---:' for _ in names) + ' |']
    for k, row in report['pass_at_k'].items():
        lines.append(f"| {k} | {len(row['eligible_task_ids'])} | " +
                     ' | '.join(_rate(row['contestants'][name]) for name in names) + ' |')
    lines += ['', 'pass@k cohorts can differ. These estimates assume exchangeable samples; repeated seeds or '
              'deterministic decoding do not establish independent draws.', '', '## Tasks', '',
              '| Task | Matched repetitions | ' + ' | '.join(names) + ' |',
              '| --- | ---: | ' + ' | '.join('---:' for _ in names) + ' |']
    for task, row in report['per_task'].items():
        n = len(row['matched_repetitions'])
        lines.append(f'| {task} | {n} | ' + ' | '.join(str(row['contestants'][name]['solved']) if n else 'unknown' for name in names) + ' |')
    grading = report.get('grading_summary') or {}
    if grading.get('llm_judged_attempts') or grading.get('calibration'):
        lines += ['', '## Grading provenance', '',
                  f"Modes: {grading.get('modes', {})}; LLM-judged attempts: {grading.get('llm_judged_attempts', 0)}; "
                  f"human-calibrated: {grading.get('human_calibrated_attempts', 0)}."]
        if grading.get('calibration'):
            cal = grading['calibration']
            lines.append(
                f"Calibration agreement: {_rate(cal.get('judge_human_agreement_rate'))} "
                f"({cal.get('override_count', 0)} overrides / {cal.get('reviewed_count', 0)} reviewed; "
                f"kappa={_num(cal.get('cohens_kappa'), '.3f')})."
            )
    lines += ['', 'Repetitions are not independent tasks. Infrastructure-failed blocks are excluded for every contestant. '
              'Timings include failures; unknown usage stays unknown. This report does not establish a general winner.', '']
    return '\n'.join(lines)
