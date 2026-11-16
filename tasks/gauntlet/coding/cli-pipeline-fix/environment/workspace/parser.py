import json
from datetime import datetime, timezone


def parse_events(text):
    events = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        item = json.loads(line)
        ts = datetime.fromisoformat(item["ts"].replace("Z", "+00:00"))
        # BUG: strips timezone instead of normalizing to UTC
        ts = ts.replace(tzinfo=None)
        dur = item.get("duration_ms", 0)  # BUG: defaults missing to 0 and skips validation
        events.append({"id": item["id"], "ts": ts, "duration_ms": dur})
    return events
