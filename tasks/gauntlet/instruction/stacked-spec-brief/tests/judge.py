"""Protected verifier for stacked-spec-brief."""
import json, re
from pathlib import Path

FORBIDDEN = ("cloud", "unlimited", "magic", "todo", "tbd")

def evaluate(candidate, isolate=True):
    p = Path(candidate)
    if p.is_symlink() or not p.is_file():
        return {"passed": 0, "total": 7}
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    passed = 0
    # 1. Exact 4 H2 headings in order
    headings = [ln.strip() for ln in lines if ln.startswith("## ")]
    if headings == ["## Summary", "## Architecture", "## Constraints", "## Checklist"]:
        passed += 1
    # 2. Summary word count 25..45
    m_sum = re.search(r"## Summary\s+(.*?)\s+## Architecture", text, flags=re.DOTALL)
    if m_sum and 25 <= len(m_sum.group(1).split()) <= 45:
        passed += 1
    # 3. Forbidden words absent
    low = text.lower()
    if not any(re.search(rf"\b{w}\b", low) for w in FORBIDDEN):
        passed += 1
    # 4. Exactly 4 sorted bullets in Checklist
    m_chk = re.search(r"## Checklist\s+(.*?)(?:```|$)", text, flags=re.DOTALL)
    if m_chk:
        bullets = [ln for ln in m_chk.group(1).splitlines() if ln.startswith("- ")]
        if len(bullets) == 4 and bullets == sorted(bullets, key=str.lower):
            passed += 1
    # 5. Exact facts
    if "8443" in text and "512MB" in text:
        passed += 1
    # 6. Trailing fenced JSON
    m_json = re.search(r"```json\s*(\{.*?\})\s*```\s*$", text, flags=re.DOTALL)
    if m_json:
        try:
            if json.loads(m_json.group(1)) == {"owner": "edge-team", "port": 8443, "ready": True}:
                passed += 1
        except ValueError:
            pass
    # 7. No trailing spaces
    if all(not ln.endswith(" ") and not ln.endswith("\t") for ln in lines):
        passed += 1
    return {"passed": passed, "total": 7}

if __name__ == "__main__":
    rep = evaluate("/workspace/brief.md", isolate=False)
    d = Path("/logs/verifier")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "checks.json").write_text(json.dumps(rep) + "\n")
    (d / "reward.txt").write_text("1" if rep["passed"] == rep["total"] else "0")
