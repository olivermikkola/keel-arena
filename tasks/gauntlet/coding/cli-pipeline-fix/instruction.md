Fix the multi-file Python CLI in `/workspace` (`parser.py`, `formatter.py`, `cli.py`).
Requirements:
1. `parser.py`: `parse_events(text)` parses JSON lines. Timestamps with offsets (`+02:00`, `-05:00`, `Z`) must be converted to UTC `datetime` objects, not stripped of timezone info. Missing `duration_ms` must stay `None` (not `0`); negative or boolean `duration_ms` must be rejected with `ValueError`.
2. `formatter.py`: `format_summary(events, min_duration=None)` must filter out events where `duration_ms is None` or `duration_ms < min_duration` when `min_duration is not None`, sort surviving events chronologically by UTC timestamp, and output JSON with `count` and `events` (where `ts` is ISO-8601 UTC ending in `Z`).
3. `cli.py`: `--min-duration N` must accept integer `N >= 0` and exit nonzero on invalid input or malformed JSONL.
