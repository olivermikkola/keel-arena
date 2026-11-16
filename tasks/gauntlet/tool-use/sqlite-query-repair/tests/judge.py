"""Protected verifier for sqlite-query-repair."""
import json
from pathlib import Path

EXPECTED = {"by_category_cents": {"books": 5200, "hardware": 4900}, "top_sku": "HW-1", "total_completed_cents": 10100}

def evaluate(candidate, isolate=True):
    p = Path(candidate)
    if p.is_symlink() or not p.is_file():
        return {"passed": 0, "total": 1}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {"passed": 1 if data == EXPECTED else 0, "total": 1}
    except Exception:
        return {"passed": 0, "total": 1}

if __name__ == "__main__":
    rep = evaluate("/workspace/report.json", isolate=False)
    d = Path("/logs/verifier")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "checks.json").write_text(json.dumps(rep) + "\n")
    (d / "reward.txt").write_text("1" if rep["passed"] == rep["total"] else "0")
