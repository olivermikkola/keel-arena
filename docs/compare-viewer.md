# Offline compare viewer

Smallest standalone shell for opening a local Arena results JSON, showing the
existing report summary surface, and linking to `dashboard.html` from cards.

## Run

```sh
# Write index.html + cards/ under a local directory (--out required; keep outside Git)
python3 -m keel_arena view examples/synthetic-gauntlet-results.json --out ./artifacts/demo-compare

# Same, then serve on loopback and open a browser (Ctrl+C to stop)
python3 -m keel_arena view examples/synthetic-gauntlet-results.json --out ./artifacts/demo-compare --serve --no-open
```

`--out` is required (same as `cards`). Prefer ignored paths such as `artifacts/` or `runs/`.
`--serve` binds `127.0.0.1` only. Use `--port N` to pin a port; omit for ephemeral.

The fixture above is `purpose: "demonstration"` — not a measured model result.

## What it shows

- Purpose badge (`demonstration` / `benchmark`)
- Matched / planned / excluded block counts from `summarize`
- Per-contestant grades, task-mean rates, and outcome counts
  (`solved` / `unsolved` / `timeout` / `infrastructure_error`)
- Provenance digests: `result_sha256`, `harness_revision`, `environment_sha256`,
  `sampling_sha256`
- Links to offline `cards/dashboard.html` and `cards/overview.svg` from
  `keel_arena.cards.write_cards`

## Boundary

Wraps `load` / `summarize` / `write_cards` only. No study runner, no model calls,
no private verifier bodies. Desktop can later embed the same bundle or call the
same library APIs; see the Project note on Desktop embed.
