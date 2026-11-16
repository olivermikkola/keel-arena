# Frontier LLM-as-a-Judge & Human Calibration

Unlike benchmarks locked to brittle deterministic checks alone, Keel Arena supports **hybrid grading** (`deterministic`, `llm_judge`, and `hybrid`) using a pinned **Frontier LLM Judge** (`keel_arena/judge.py`) paired with **post-test human calibration**.

## Design principles

1. **Blinded evaluation:** Contestant names, model IDs, quantizations, and harnesses are stripped before judging (`sub-0001`, `CANDIDATE_A`/`CANDIDATE_B`).
2. **Prompt-injection containment:** Untrusted agent artifacts are bounded to 64 KiB and wrapped in explicit `<SUBMISSION_ARTIFACT>` tags with system-level isolation instructions.
3. **Deterministic judge configuration:** Forces `temperature=0.0`, `top_p=1.0`, and explicit `seed` per submission against a content-hashed `rubric-v1` JSON (`rubric_sha256`).
4. **Explicit gate policy:**
   - `deterministic_gate: "required"` — deterministic checks must pass for `passed: true`, while the frontier judge scores nuance and quality.
   - `deterministic_gate: "advisory"` / `"none"` — deterministic checks serve as context; the frontier LLM judge determines `passed` (ideal for open-ended reasoning, code reviews, and prose quality).
5. **Position-swapped Pairwise Elo (`judge-pairwise`):** Every `(task, repetition)` pair is evaluated in both `(A, B)` and `(B, A)` orders. Position-inconsistent pairs become `tie` with `position_consistent: false` so position bias cannot inflate Elo ratings.

## Human Calibration & Post-Test Overrides

After reviewing a sample or overall benchmark run, humans can record corrections in an immutable override file (`schema_version: 1`):

```json
{
  "schema_version": 1,
  "reviews": [
    {
      "task": "code-review-patch-notes",
      "contestant": "candidate-a",
      "repetition": 0,
      "human_passed": true,
      "human_score": 0.85,
      "reviewer_note": "Valid alternative formatting missed by strict check"
    }
  ]
}
```

Apply calibration without mutating the original judge ledger, computing **Judge-Human Agreement Rate** and **Cohen's kappa**:

```sh
python3 -m keel_arena calibrate judge-ledger.json --overrides human-overrides.json --results results.json --out calibrated.json
```
