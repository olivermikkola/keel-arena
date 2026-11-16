import json
from datetime import datetime, timezone


def parse_events(text):
    events = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        item = json.loads(line)
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("ts"), str):
            raise ValueError("invalid event record")
        ts = datetime.fromisoformat(item["ts"].replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        dur = item.get("duration_ms")
        if dur is not None:
            if type(dur) is not int or dur < 0:
                raise ValueError("invalid duration_ms")
        events.append({"id": item["id"], "ts": ts, "duration_ms": dur})
    return events
