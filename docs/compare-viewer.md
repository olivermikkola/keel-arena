# Offline compare viewer

Standalone shell for opening local Arena artifacts: a single results JSON, or a
paired compare of two saved runs (Arena results JSON **or** Keel Mobile harness-eval
dirs). Wraps `load` / `summarize` / `write_cards` and `keel_mobile.compare_runs`.

## Single run

```sh
# Write index.html + cards/ under a local directory (--out required; keep outside Git)
python3 -m keel_arena view examples/synthetic-gauntlet-results.json --out ./artifacts/demo-compare

# Same, then serve on loopback and open a browser (Ctrl+C to stop)
python3 -m keel_arena view examples/synthetic-gauntlet-results.json --out ./artifacts/demo-compare --serve --no-open
```

## Paired runs

Pass `--against` for a second artifact of the **same kind**. The viewer writes
`index.html`, `paired.json`, and `manifest.json` under `--out`.

### Two Arena results JSON files

```sh
python3 -m keel_arena view examples/synthetic-results.json \
  --against examples/synthetic-results-paired-b.json \
  --out ./artifacts/demo-paired-results \
  --left-label base --right-label adapted
```

Shows protocol / `result_sha256` diffs, changed `(task, contestant, repetition)`
outcomes, timeouts, infrastructure exclusions, and links to per-run
`left/cards/dashboard.html` and `right/cards/dashboard.html`.

### Two Keel Mobile run directories

```sh
python3 -m keel_arena view examples/synthetic-keel-mobile/base-run \
  --against examples/synthetic-keel-mobile/adapted-run \
  --out ./artifacts/demo-paired-mobile \
  --left-label base --right-label adapted
```

Reuses `compare_runs` (same engine as `compare-keel-mobile`): setup diffs,
changed tasks, timeouts, infra exclusions, and speed-shift warnings. Optional
`--suites`, `--left-setup` / `--right-setup` work as on `compare-keel-mobile`.

Serve either paired bundle with `--serve` / `--port` / `--no-open` the same way.

`--out` is required (same as `cards`). Prefer ignored paths such as `artifacts/`
or `runs/`. `--serve` binds `127.0.0.1` only.

Public fixtures above are `purpose: "demonstration"` — not measured model results.

## What it shows

**Single run**

- Purpose badge (`demonstration` / `benchmark`)
- Matched / planned / excluded block counts from `summarize`
- Per-contestant grades, task-mean rates, and outcome counts
  (`solved` / `unsolved` / `timeout` / `infrastructure_error`)
- Provenance digests: `result_sha256`, `harness_revision`, `environment_sha256`,
  `sampling_sha256`
- Links to offline `cards/dashboard.html` and `cards/overview.svg`

**Paired runs**

- Purpose badges for both sides
- Headline solved rates and paired solved counts
- Provenance / setup diffs (protocol digests for Arena JSON; model / harness /
  sampler / server / declared setup for Keel Mobile)
- Changed tasks (outcome matrix diffs)
- Timeouts and infrastructure exclusions
- Warnings already emitted by `compare_runs` (or Arena digest mismatch notes)
- Per-run dashboards when both sides are Arena results JSON

## Boundary

No study runner, no model calls, no private verifier bodies. Desktop can later
embed the same bundle or call the same library APIs; see the Project note on
Desktop embed. For Markdown-only Mobile reports without HTML, keep using
`compare-keel-mobile --format markdown`.
