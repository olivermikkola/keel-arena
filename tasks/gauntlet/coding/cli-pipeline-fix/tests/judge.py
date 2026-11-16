"""Protected verifier for cli-pipeline-fix."""
import json, os, shutil, signal, subprocess, sys, tempfile
from pathlib import Path

CASES = [
    (
        '{"id":"b","ts":"2026-01-01T12:00:00+02:00","duration_ms":150}\n'
        '{"id":"a","ts":"2026-01-01T10:30:00Z"}\n'
        '{"id":"c","ts":"2026-01-01T05:30:00-05:00","duration_ms":200}\n',
        ["--min-duration", "100"],
        0,
        {"count": 2, "events": [
            {"id": "b", "ts": "2026-01-01T10:00:00Z", "duration_ms": 150},
            {"id": "c", "ts": "2026-01-01T10:30:00Z", "duration_ms": 200},
        ]},
    ),
    (
        '{"id":"a","ts":"2026-01-01T10:30:00Z"}\n',
        [],
        0,
        {"count": 1, "events": [{"id": "a", "ts": "2026-01-01T10:30:00Z", "duration_ms": None}]},
    ),
    ('{"id":"bad","ts":"2026-01-01T10:00:00Z","duration_ms":true}\n', [], 2, None),
    ('{"id":"bad","ts":"2026-01-01T10:00:00Z","duration_ms":-5}\n', [], 2, None),
]

def evaluate(workspace_dir, isolate=True):
    ws = Path(workspace_dir)
    for fn in ("parser.py", "formatter.py", "cli.py"):
        p = ws / fn
        if p.is_symlink() or not p.is_file():
            return {"passed": 0, "total": len(CASES)}
    if isolate and os.geteuid() != 0:
        raise RuntimeError("protected verification requires root")
    passed = 0
    with tempfile.TemporaryDirectory() as tmp:
        os.chmod(tmp, 0o755)
        for fn in ("parser.py", "formatter.py", "cli.py"):
            shutil.copy2(ws / fn, Path(tmp) / fn)
        for idx, (payload, flags, exp_code, exp_json) in enumerate(CASES):
            infile = Path(tmp) / f"in_{idx}.jsonl"
            infile.write_text(payload, encoding="utf-8")
            opts = {"user": 65534, "group": 65534, "extra_groups": []} if isolate else {}
            proc = subprocess.Popen(
                [sys.executable, str(Path(tmp) / "cli.py"), str(infile), *flags],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=tmp,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, start_new_session=True, **opts
            )
            try:
                out, _ = proc.communicate(timeout=2)
                if exp_code != 0:
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
    return {"passed": passed, "total": len(CASES)}

if __name__ == "__main__":
    if os.geteuid() != 0:
        raise SystemExit("protected verifier requires root")
    rep = evaluate("/workspace")
    d = Path("/logs/verifier")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "checks.json").write_text(json.dumps(rep) + "\n")
    (d / "reward.txt").write_text("1" if rep["passed"] == rep["total"] else "0")
