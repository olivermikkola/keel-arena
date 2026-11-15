# Import Harbor results

Arena can read single-step Harbor **0.26.0** trial artifacts without installing
Harbor, contacting providers or executing task content. This imports actual trial
files; it does not launch trials. Native task generation and execution stay in
Harbor. Multi-step, regraded and setup-only trials are refused in this version.

```sh
python3 -m keel_arena import-harbor "$ARENA_BINDINGS" --jobs-root "$HARBOR_JOBS" > "$ARENA_RESULT_FILE"
python3 -m keel_arena report "$ARENA_RESULT_FILE"
```

Keep both environment-variable values and outputs private. The input manifest is
an object with these exact fields:

- `schema_version`: integer 1.
- `harbor_version`: string `0.26.0` (the operator's pinned execution version).
- `reward_metric`: one binary verifier metric, normally `reward`.
- `plan`: the v1 result contract without `attempts`. Freeze the full task/model/
  repetition matrix, sampling, environment and budget before execution.
- `trials`: one explicit binding for every planned cell. Each binding has `task`,
  `contestant`, zero-based `repetition`, `directory` relative to `--jobs-root`,
  `task_checksum` (Harbor's native checksum) and `config_sha256`.

`config_sha256` is Arena's canonical SHA-256 of the exact serialized Harbor
`TrialConfig` object in `result.json`, including defaults. The caller must freeze
resolved configs before execution and record their correspondence to the Arena
model/task manifests. Do not compute a replacement binding from whatever config
happened to run after inspecting its score. Arena verifies matching bytes, not
when the commitment was made or whether a model provider is honest.

The importer reads only `result.json`, `verifier/reward.txt` or `reward.json`, and
optional `agent/trajectory.json` within each bound directory. It refuses path
traversal, symlinks, unknown/reused cells, mismatched configs/tasks, unfinished
trials, missing or inconsistent rewards, and nonbinary/multiple reward metrics.
It never follows paths or URIs from backend JSON. Each file is limited to 16 MiB.

`AgentTimeoutError` becomes `timeout`. Known agent failures (nonzero agent exit,
context/output exhaustion and refusals) retain their protected grading outcome,
following the reviewed Harbor 0.26.0 error table. Other exceptions become
`infrastructure_error`, even if the result also carries a passing reward. This
conservative policy may exclude valid model failures for an unknown exception;
add an explicit reviewed classification when integrating another backend error.
A run with no exception must have `reward_valid: true` and a reward artifact
agreeing with the serialized verifier result. Missing evidence is an import error,
not a fabricated model failure. A failed environment with no execution timestamps
can still be represented using its overall trial start/end timestamps.

Wall time is overall trial elapsed time, including setup and grading, consistently
for every attempt. `verifier_result_sha256` identifies the original `result.json` bytes for graded
outcomes, so it binds the reward to its task, configuration and timing. The reward
artifact is independently checked for agreement. Token counts are copied from single-step `agent_result`, with
unknown values preserved. Trajectory bytes are hashed when available; this does
not validate ATIF or make them suitable training data. Source result and verifier
artifacts must remain in the operator's private evidence store.

See [competitive research](competitive-research.md) for the source-backed choices.
