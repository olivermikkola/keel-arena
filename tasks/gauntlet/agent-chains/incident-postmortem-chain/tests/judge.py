"""Protected verifier for incident-postmortem-chain."""
import json
from pathlib import Path

EXPECTED = {"affected_service": "auth-proxy", "faulty_commit": "c9f2a1d", "peak_error_rate_pct": 24.5, "rollback_commit": "d4e5f6a"}

def evaluate(ws_dir, isolate=True):
    ws = Path(ws_dir)
    passed = 0
    try:
        j = json.loads((ws / "postmortem.json").read_text(encoding="utf-8"))
        if j == EXPECTED:
            passed += 1
        md = (ws / "postmortem.md").read_text(encoding="utf-8")
        if "c9f2a1d" in md and "auth-proxy" in md and len(md.split()) >= 15:
            passed += 1
    except Exception:
        pass
    return {"passed": passed, "total": 2}

if __name__ == "__main__":
    rep = evaluate("/workspace", isolate=False)
    d = Path("/logs/verifier")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "checks.json").write_text(json.dumps(rep) + "\n")
    (d / "reward.txt").write_text("1" if rep["passed"] == rep["total"] else "0")
