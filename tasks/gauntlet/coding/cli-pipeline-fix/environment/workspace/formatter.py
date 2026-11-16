import json


def format_summary(events, min_duration=None):
    # BUG: ignores min_duration and sorts by raw string/naive ts
    ordered = sorted(events, key=lambda e: str(e["ts"]))
    out = [{"id": e["id"], "ts": e["ts"].isoformat(), "duration_ms": e["duration_ms"]} for e in ordered]
    return json.dumps({"count": len(out), "events": out})
