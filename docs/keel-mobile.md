# Compare saved Keel Mobile eval runs

Keel Mobile's `tools/harness-eval` agent eval exports one JSON object per
`(task, sample)` attempt when given `--out SUITE.jsonl`, and prints setup headers
and a summary when piped to `SUITE.txt`. Arena can pair two saved run directories
(or two single `.jsonl` files) offline, without rerunning inference, contacting a
server or executing task content.

```sh
python3 -m keel_arena compare-keel-mobile \
  examples/synthetic-keel-mobile/base-run \
  --against examples/synthetic-keel-mobile/adapted-run \
  --format markdown
```

The synthetic fixture under `examples/synthetic-keel-mobile/` is a small
deliberate demonstration (`purpose` is local comparison, not measured model
data). Keep real evaluation runs and raw transcripts outside public Git.

## Expected run layout

A saved run directory typically contains:

- `SUITE.jsonl`: per-attempt `Outcome` rows written by `tools/harness-eval`
  (`work.jsonl`, `chat.jsonl`, `repo.jsonl`, `edit.jsonl`, or sharded names such
  as `repo-1.jsonl`).
- `SUITE.txt` (optional): stdout header (`model:`, `sampler:`) and final summary
  (`all N/M passed`), used to verify declared flags and suite completion.
- `model.sha256` (optional): SHA-256 digest and filename of the evaluated GGUF.
- `keel-mobile-commit.txt` (optional, in the run directory or its parent):
  40-character Git commit SHA of the Keel Mobile checkout.
- `server.log` or `server.txt` (optional): `llama-server` log for thread count,
  slots, context per slot, backend hints and observed prompt/generation `tok/s`.

You can also pass two `.jsonl` files directly to compare a single suite file.

## What the paired report checks

1. **Where the setups differ**: compares `model_sha256`, `model_file`,
   `harness_commit`, `eval.*` header settings, `sampler.*` parameters, `server.*`
   settings, and any operator-declared `--left-setup key=value` /
   `--right-setup key=value` tags.
   - If observed prompt or generation speed in `server.log` shifts by `1.5x` or
     more without a declared setup difference (for example, switching from CPU to
     a Vulkan iGPU when `server.log` does not print a device banner), Arena emits
     a warning so backend changes are not mistaken for silent reruns.
   - If neither recorded nor declared setup fields differ, Arena warns that score
     changes cannot be attributed to a recorded setup change.
   - If `harness_commit` differs or is missing, Arena warns that task order,
     seeds, prompts or checks may not match.
   - If a suite lacks its completion summary or expected attempt count, Arena
     warns that the suite is incomplete.
2. **Outcome classification**:
   - Budget stops (`tool limit`, `invalid call at limit`,
     `call cut off by the reply limit`, `context overflow`) and request timeouts
     (`URLError -1001` / `timed out`) map to `timeout` with a bounded stop reason
     (`step_limit`, `reply_limit`, `context_limit`, `request_timeout`).
   - Malformed tool calls (`invalid call: ...`, `tool failure: call`) remain
     graded `unsolved` attempts (`invalid_call`).
   - Harness or check failures (`check could not run...`, unexpected
     `tool failure:` or `error:`) map to `infrastructure_error` and exclude that
     `(suite, task, sample)` cell from both sides of the paired totals.
3. **Tasks that changed and timeouts**: lists every task whose per-sample
   outcome label changed between left and right, ordered by the magnitude of the
   solved-count difference, followed by every matched cell that timed out on
   either side and any excluded or one-sided cells.
4. **Harness counters**: aggregates matched tool steps, generated and prefill
   tokens, rejected calls, JSON-wrapped calls, tool errors, `run_js` script
   calls, narration characters before tool calls, cache misses and wall seconds.

## Options

- `--against PATH`: required right-hand run directory or `.jsonl` file.
- `--suites s1,s2`: compare only the named suites (must exist in both runs). By
  default, compares every suite present in both runs and lists unmatched suites
  under `Not compared`.
- `--left-setup key=value` / `--right-setup key=value`: repeatable tags for
  setup facts not captured in `server.log` (such as `backend=cpu` vs
  `backend=vulkan-radv`).
- `--left-label NAME` / `--right-label NAME`: override display labels.
- `--format json|markdown`: machine-readable JSON (default) or Markdown table
  report.
- `--out PATH`: write the report to a file instead of stdout.
