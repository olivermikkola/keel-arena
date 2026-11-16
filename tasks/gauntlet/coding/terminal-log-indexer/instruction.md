Create `/workspace/indexer.py` per `/workspace/SPEC.md`.
CLI contract:
`python3 /workspace/indexer.py --input <logfile> [--level INFO|WARN|ERROR] [--since ISO_Z] --json`
Output JSON keys: `total` (int), `by_level` (object mapping `INFO`, `WARN`, `ERROR` counts for matching rows, omitting zeros or keeping zero only if needed — see SPEC.md: include all three keys `INFO`, `WARN`, `ERROR` with integer counts), `latest_ts` (ISO `Z` string of latest matching entry or `null`).
Exit nonzero (e.g. 2) if `--input` is missing/unreadable or `--level` is invalid. Ignore malformed log lines instead of crashing.
