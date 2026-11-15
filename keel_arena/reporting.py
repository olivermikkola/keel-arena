"""Readable local reports; never uploads or chooses a winning model."""


def _rate(value):
    return 'unknown' if value is None else f'{value:.1%}'


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
    lines += ['', 'Repetitions are not independent tasks. Infrastructure-failed blocks are excluded for every contestant. '
              'Timings include failures; unknown usage stays unknown. This report does not establish a general winner.', '']
    return '\n'.join(lines)
