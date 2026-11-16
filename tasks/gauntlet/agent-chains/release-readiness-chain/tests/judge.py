"""Protected verifier for release-readiness-chain."""
import json
from pathlib import Path

def evaluate(ws_dir, isolate=True):
    ws = Path(ws_dir)
    bundle = ws / "release_bundle.json"
    svc = ws / "services.json"
    env_p = ws / "target.env"
    if not bundle.is_file() or bundle.is_symlink():
        bundle = ws / "release_bundle.json"
    passed = 0
    try:
        b = json.loads((ws / "release_bundle.json").read_text())
        if b == {"release": "2.4.0", "services": {"auth": "2.4.0", "billing": "2.4.1"}, "checks_passed": True}:
            passed += 1
        s = json.loads((ws / "services.json" if (ws / "services.json").exists() else ws / "manifests/services.json").read_text())
        if s.get("services") == {"auth": "2.4.0", "billing": "2.4.1"}:
            passed += 1
        ep = ws / "target.env" if (ws / "target.env").exists() else ws / "deploy/target.env"
        if "BILLING_PORT=9200" in ep.read_text():
            passed += 1
    except Exception:
        pass
    return {"passed": passed, "total": 3}

if __name__ == "__main__":
    rep = evaluate("/workspace", isolate=False)
    d = Path("/logs/verifier")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "checks.json").write_text(json.dumps(rep) + "\n")
    (d / "reward.txt").write_text("1" if rep["passed"] == rep["total"] else "0")
