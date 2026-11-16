"""Protected verifier for config-migration-schema."""
import json
from pathlib import Path

EXPECTED = {
    "allowed_origins": ["https://admin.example", "https://app.example"],
    "port": 8443,
    "rejected_origins": ["http://insecure.example"],
    "tls": True,
}

def evaluate(candidate, isolate=True):
    p = Path(candidate)
    if p.is_symlink() or not p.is_file():
        return {"passed": 0, "total": 1}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ok = (data == EXPECTED and type(data["port"]) is int and type(data["tls"]) is bool)
        return {"passed": 1 if ok else 0, "total": 1}
    except Exception:
        return {"passed": 0, "total": 1}

if __name__ == "__main__":
    rep = evaluate("/workspace/migrated.json", isolate=False)
    d = Path("/logs/verifier")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "checks.json").write_text(json.dumps(rep) + "\n")
    (d / "reward.txt").write_text("1" if rep["passed"] == rep["total"] else "0")
