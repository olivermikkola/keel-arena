"""Protected verifier for chronological-policy-override."""
import json
from pathlib import Path

EXPECTED = {"audit_region": "eu-west-1", "max_retry_attempts": 4, "satellite_uplink_key": "unknown"}

def evaluate(candidate, isolate=True):
    p = Path(candidate)
    if p.is_symlink() or not p.is_file():
        return {"passed": 0, "total": 1}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ok = data == EXPECTED and type(data["max_retry_attempts"]) is int
        return {"passed": 1 if ok else 0, "total": 1}
    except Exception:
        return {"passed": 0, "total": 1}

if __name__ == "__main__":
    rep = evaluate("/workspace/answers.json", isolate=False)
    d = Path("/logs/verifier")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "checks.json").write_text(json.dumps(rep) + "\n")
    (d / "reward.txt").write_text("1" if rep["passed"] == rep["total"] else "0")
