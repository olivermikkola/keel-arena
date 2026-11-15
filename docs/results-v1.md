# Result contract v1

The executable validator is `keel_arena/results.py`; the complete small example is
`examples/synthetic-results.json`. Unknown fields are rejected at every level.
Inputs must be UTF-8 JSON, at most 16 MiB, without duplicate keys or nonfinite
numeric values. CLI exit code 0 means success, 2 means invalid/unreadable input.
CLI errors withhold input values and paths; Python API validation errors describe
the failed field. Reports use JSON on stdout.

## Fields

| Object | Required fields |
| --- | --- |
| Root | `schema_version` (integer 1), `purpose`, `protocol`, `tasks`, `contestants`, `repetitions`, `attempts` |
| Protocol | `harness_revision`, `environment_sha256`, `sampling_sha256`, `budget` |
| Budget | Positive integer `max_steps`, `max_output_tokens`, `timeout_seconds` |
| Tasks | Nonempty map of public-safe or locally pseudonymous task IDs to task objects |
| Task | `snapshot_sha256`, `verifier_sha256`, `split` |
| Contestants | Nonempty map of contestant IDs to contestant objects |
| Contestant | `model_revision_sha256`, `quantization` |
| Attempt | `task`, `contestant`, `repetition`, `outcome`, `wall_seconds`, `input_tokens`, `output_tokens`, `trajectory_sha256`, `verifier_result_sha256` |

`purpose` is `demonstration` or `benchmark`. Never change a synthetic fixture to
`benchmark` to suggest it was measured. Task split is `train`, `development` or
`test`; one file must use a single split. IDs and quantization labels match
`[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}`. They must not contain paths or endpoint URLs.
All digests are lowercase 64-character SHA-256 hex strings.

Despite its name, `harness_revision` is the executable's SHA-256, not a Git SHA.
Keep source revision, build settings and executable provenance in the private
manifest. Model digest identifies an immutable artifact manifest (revision,
weights, tokenizer and quantization). Environment and sampling digests identify
frozen manifests, including tool/runtime versions, prompt policy, context limits,
seeds and actual sampling configuration. Freeze those files and the task matrix
before execution. Arena checks declarations and structure, not whether an operator
truthfully executed them. Backend evidence must establish compliance.

Each planned `(task, contestant, repetition)` must appear exactly once. Repetitions
are indexed from zero; the maximum matrix is 100,000 attempts across at most 64 contestants. No partial reports
or silent omission of failed attempts. Token counts are nonnegative integers or
`null` (unknown). Wall time is a finite nonnegative number, capped at 1e15 seconds
as an input sanity check. A measured timeout may include cleanup overhead.

## Outcomes and evidence

- `solved`: the protected task verifier confirmed the requested final state.
- `unsolved`: grading completed but final state did not meet the task criteria.
- `timeout`: the attempt exhausted its declared budget without verified success.
- `infrastructure_error`: execution/grading was invalid because its environment
  failed. Never use this to hide an ordinary unsuccessful model attempt.

Solved and unsolved outcomes require `verifier_result_sha256`. Trajectory hashes
and verifier hashes for the other outcomes may be `null`. Missing trajectories
can still support scoring, but cannot support a training export. Hashes identify
private evidence; they do not prove correctness or grant publication permission.

An infrastructure error removes its entire task/repetition block from matched
comparisons for every contestant. Raw outcome counts remain visible. A timeout
counts as unsolved in the matched solve-rate denominator. If no blocks are
eligible, solve rate is `null`, not zero. Independent-task count and repetition
block counts are reported separately.

Token totals are `null` if any eligible attempt lacks the corresponding count.
Time and usage totals include failures in eligible blocks. Pairwise counts show
which contestant solved a block the other missed; union coverage is an oracle
upper bound from all attempts, not an executable routing strategy or ensemble
score. Different model tokenizers make raw token totals imperfect cost proxies.
No significance or generalization claim is inferred from these counts.

`result_sha256` hashes the parsed normalized input serialized with Python's
`json.dumps(sort_keys=True, separators=(",", ":"), allow_nan=False)` encoded as
UTF-8 (default ASCII escaping). It is not the source file byte hash; JSON number
representations such as `10` and `10.0` remain distinct. Reports retain `purpose`
so demonstrations remain distinguishable downstream.
