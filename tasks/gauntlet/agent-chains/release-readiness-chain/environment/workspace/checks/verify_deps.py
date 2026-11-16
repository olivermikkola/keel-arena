import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
svc = json.loads((root / "manifests/services.json").read_text())
env = dict(line.split("=", 1) for line in (root / "deploy/target.env").read_text().splitlines() if "=" in line)
errors = []
if svc.get("services", {}).get("auth") != "2.4.0":
    errors.append("auth version must be 2.4.0")
if svc.get("services", {}).get("billing") != "2.4.1":
    errors.append("billing version must be 2.4.1")
if env.get("AUTH_PORT") != "9100":
    errors.append("AUTH_PORT must be 9100")
if env.get("BILLING_PORT") != "9200":
    errors.append("BILLING_PORT must be 9200")
if errors:
    print("FAIL:", "; ".join(errors))
    raise SystemExit(1)
print("OK: all release dependencies verified")
