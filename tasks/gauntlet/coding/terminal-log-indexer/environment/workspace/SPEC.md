# Log Indexer Spec
Input log lines have format:
`YYYY-MM-DDTHH:MM:SSZ LEVEL message text`
Only levels `INFO`, `WARN`, `ERROR` are valid. Ignore blank or malformed lines.
When `--level` is supplied, keep only entries matching that level.
When `--since` is supplied (ISO-8601 UTC ending in `Z`), keep entries with `ts >= since`.
JSON output must contain exact keys: `total`, `by_level` (`{"ERROR": int, "INFO": int, "WARN": int}`), `latest_ts` (string or null).
