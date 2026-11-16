"""Protected verifier for api-contract-recovery."""
import json
from pathlib import Path

EXPECTED = {"item_ids": ["m-01", "m-02", "m-03", "m-04", "m-05", "m-06", "m-07"], "sum_values": 137}

def evaluate(candidate, isolate=True):
    p = Path(candidate)
    if p.is_symlink() or not p.is_file():
        return {"passed": 0, "total": 1}
    try:
        return {"passed": 1 if json.loads(p.read_text(encoding="utf-8")) == EXPECTED else 0, "total": 1}
    except Exception:
        return {"passed": 0, "total": 1}

if __name__ == "__main__":
    rep = evaluate("/workspace/summary.json", isolate=False)
    d = Path("/logs/verifier")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "checks.json").write_text(json.dumps(rep) + "\n")
    (d / "reward.txt").write_text("1" if rep["passed"] == rep["total"] else "0")
