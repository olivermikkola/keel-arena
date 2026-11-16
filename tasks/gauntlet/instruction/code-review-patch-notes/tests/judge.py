"""Protected verifier for code-review-patch-notes."""
import re
from pathlib import Path
import json

def evaluate(candidate, isolate=True):
    p = Path(candidate)
    if p.is_symlink() or not p.is_file():
        return {"passed": 0, "total": 5}
    text = p.read_text(encoding="utf-8")
    low = text.lower()
    passed = 0
    headings = [ln.strip() for ln in text.splitlines() if ln.startswith("## ")]
    if headings == ["## Findings", "## Verdict"]:
        passed += 1
    if "injection" in low and ("leak" in low or "close" in low) and ("off-by-one" in low or "extra" in low or "size + 1" in low):
        passed += 1
    numbered = [ln for ln in text.splitlines() if re.match(r"^[123]\.\s+", ln) and ("HIGH" in ln or "MEDIUM" in ln)]
    if len(numbered) == 3:
        passed += 1
    if any(ln.strip() == "REQUEST_CHANGES" for ln in text.splitlines()):
        passed += 1
    if len(text.split()) <= 220:
        passed += 1
    return {"passed": passed, "total": 5}

if __name__ == "__main__":
    rep = evaluate("/workspace/review.md", isolate=False)
    d = Path("/logs/verifier")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "checks.json").write_text(json.dumps(rep) + "\n")
    (d / "reward.txt").write_text("1" if rep["passed"] == rep["total"] else "0")
