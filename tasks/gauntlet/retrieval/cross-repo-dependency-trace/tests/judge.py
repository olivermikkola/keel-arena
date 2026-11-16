"""Protected verifier for cross-repo-dependency-trace."""
import json
from pathlib import Path

EXPECTED = {
    "active_path": ["gateway", "auth-edge", "token-broker", "ledger-proxy", "ledger-db"],
    "deprecated_hop": "legacy-cache",
    "offline_node": "decoy-bus",
}

def evaluate(candidate, isolate=True):
    p = Path(candidate)
    if p.is_symlink() or not p.is_file():
        return {"passed": 0, "total": 1}
    try:
        return {"passed": 1 if json.loads(p.read_text(encoding="utf-8")) == EXPECTED else 0, "total": 1}
    except Exception:
        return {"passed": 0, "total": 1}

if __name__ == "__main__":
    rep = evaluate("/workspace/trace_report.json", isolate=False)
    d = Path("/logs/verifier")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "checks.json").write_text(json.dumps(rep) + "\n")
    (d / "reward.txt").write_text("1" if rep["passed"] == rep["total"] else "0")
