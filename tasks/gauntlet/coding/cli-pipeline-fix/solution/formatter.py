import json


def format_summary(events, min_duration=None):
    filtered = events
    if min_duration is not None:
        filtered = [e for e in events if e["duration_ms"] is not None and e["duration_ms"] >= min_duration]
    ordered = sorted(filtered, key=lambda e: (e["ts"], e["id"]))
    out = [
        {
            "id": e["id"],
            "ts": e["ts"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_ms": e["duration_ms"],
        }
        for e in ordered
    ]
    return json.dumps({"count": len(out), "events": out}, sort_keys=True)
