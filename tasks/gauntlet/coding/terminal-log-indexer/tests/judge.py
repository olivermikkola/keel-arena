"""Protected verifier for terminal-log-indexer."""
import json, os, signal, subprocess, sys, tempfile
from pathlib import Path

LOG = (
    "2026-11-01T10:00:00Z INFO booted\n"
    "not a valid log line\n"
    "2026-11-01T10:05:00Z WARN slow query\n"
    "2026-11-01T10:10:00Z ERROR timeout\n"
    "2026-11-01T10:12:00Z WARN retry\n"
)

def evaluate(candidate, isolate=True):
    p = Path(candidate)
    if p.is_symlink() or not p.is_file():
        return {"passed": 0, "total": 4}
    if isolate and os.geteuid() != 0:
        raise RuntimeError("protected verification requires root")
    passed = 0
    with tempfile.TemporaryDirectory() as tmp:
        os.chmod(tmp, 0o755)
        logf = Path(tmp) / "test.log"
        logf.write_text(LOG, encoding="utf-8")
        cases = [
            (["--input", str(logf), "--json"], 0, {"total": 4, "by_level": {"INFO": 1, "WARN": 2, "ERROR": 1}, "latest_ts": "2026-11-01T10:12:00Z"}),
            (["--input", str(logf), "--level", "WARN", "--json"], 0, {"total": 2, "by_level": {"INFO": 0, "WARN": 2, "ERROR": 0}, "latest_ts": "2026-11-01T10:12:00Z"}),
            (["--input", str(logf), "--since", "2026-11-01T10:06:00Z", "--json"], 0, {"total": 2, "by_level": {"INFO": 0, "WARN": 1, "ERROR": 1}, "latest_ts": "2026-11-01T10:12:00Z"}),
            (["--input", str(Path(tmp) / "missing.log"), "--json"], 2, None),
        ]
        opts = {"user": 65534, "group": 65534, "extra_groups": []} if isolate else {}
        for flags, exp_rc, exp_json in cases:
            proc = subprocess.Popen(
                [sys.executable, "-I", str(p), *flags],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=tmp,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, start_new_session=True, **opts
            )
            try:
                out, _ = proc.communicate(timeout=2)
                if exp_rc != 0:
                    if proc.returncode != 0:
                        passed += 1
                elif proc.returncode == 0 and json.loads(out.decode()) == exp_json:
                    passed += 1
            except Exception:
                pass
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
    return {"passed": passed, "total": 4}

if __name__ == "__main__":
    if os.geteuid() != 0:
        raise SystemExit("protected verifier requires root")
    rep = evaluate("/workspace/indexer.py")
    d = Path("/logs/verifier")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "checks.json").write_text(json.dumps(rep) + "\n")
    (d / "reward.txt").write_text("1" if rep["passed"] == rep["total"] else "0")
