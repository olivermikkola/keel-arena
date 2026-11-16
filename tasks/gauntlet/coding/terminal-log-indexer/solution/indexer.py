import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+(INFO|WARN|ERROR)\s+(.+)$")


def parse_ts(value):
    if not value.endswith("Z"):
        raise ValueError("UTC Z timestamp required")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--level", choices=("INFO", "WARN", "ERROR"), default=None)
    p.add_argument("--since", default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        since_dt = parse_ts(args.since) if args.since else None
        raw = Path(args.input).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return 2
    counts = {"INFO": 0, "WARN": 0, "ERROR": 0}
    latest = None
    total = 0
    for line in raw.splitlines():
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        ts_str, lvl, _ = m.groups()
        try:
            dt = parse_ts(ts_str)
        except ValueError:
            continue
        if args.level and lvl != args.level:
            continue
        if since_dt and dt < since_dt:
            continue
        counts[lvl] += 1
        total += 1
        if latest is None or dt > latest:
            latest = dt
    out = {
        "total": total,
        "by_level": counts,
        "latest_ts": latest.strftime("%Y-%m-%dT%H:%M:%SZ") if latest else None,
    }
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
