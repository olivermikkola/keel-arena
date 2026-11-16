"""Protected verifier for invoice-normalization."""
import json
from pathlib import Path

EXPECTED = {
    "rejected_ids": ["INV-3", "INV-4"],
    "valid": [
        {"invoice_id": "INV-1", "vendor": "Alpha Co", "amount_cents": 1550, "updated_at": "2026-10-01T12:00:00Z"},
        {"invoice_id": "INV-2", "vendor": "North, LLC", "amount_cents": 1425, "updated_at": "2026-10-01T10:00:00Z"},
    ],
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
    rep = evaluate("/workspace/normalized.json", isolate=False)
    d = Path("/logs/verifier")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "checks.json").write_text(json.dumps(rep) + "\n")
    (d / "reward.txt").write_text("1" if rep["passed"] == rep["total"] else "0")
