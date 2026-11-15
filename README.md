# Keel Arena

Reproducible coding-agent benchmarks. Compare models inside the same harness,
measure completed tasks, and preserve the evidence behind every result.

**Public tooling. Private evaluations. Training stays downstream.**

## Current status

Version 0.1 provides a dependency-free Python CLI for validating normalized results
and comparing complete, matched task/repetition blocks. It reports solve rates,
time, known token usage, and complementary successes between models.

It also [imports Harbor 0.26.0 trial evidence](docs/harbor-import.md), checking
explicit bindings and protected reward artifacts before normalizing results.
The [Harbor Keel adapter](docs/keel-agent.md) launches a pinned private executable
inside a backend task environment, with a bounded provider wrapper and private
request/response evidence. Arena does not provision its own sandbox or train models. No real-model leaderboard or model improvement is claimed. The included
fixture is entirely synthetic and tests reporting behavior only.

## Try it

Requires Python 3.11 or later. No installation, accounts, network, model server,
containers or API credits are needed:

```sh
python3 -m keel_arena validate examples/synthetic-results.json
python3 -m keel_arena report examples/synthetic-results.json
python3 -m unittest discover -s tests -v
python3 scripts/check_publication.py
```

The demonstration has three tasks and two fictional contestants. An infrastructure
error excludes one task/repetition block for both contestants. Each solves one of
the two remaining tasks; together they cover both. Those numbers describe a
reporting fixture, not model performance. Unknown token counts remain `null`.

An optional local install (`python3 -m pip install .`) adds `keel-arena`. This may
fetch the pinned build backend; running directly from the checkout needs only
the standard library. There is no published package release yet.

## Use private tasks and results

Keep task banks, source snapshots, model identity manifests, raw trajectories,
patches and verifier evidence outside this checkout. Ignored `private/`, `runs/`
and `artifacts/` directories are available for local work, but ignoring a path
cannot sanitize files copied elsewhere.

Point Arena at a local normalized result file:

```sh
python3 -m keel_arena validate "$ARENA_RESULT_FILE"
python3 -m keel_arena report "$ARENA_RESULT_FILE" > "$ARENA_REPORT_FILE"
```

The reporting/import CLI reads local files and writes to stdout. It executes no commands from result input, loads no plugins, calls no providers
and uploads nothing. Explicit execution through Harbor is a separate opt-in path. Reports remain private
until you deliberately share them. They retain contestant identifiers and hashes,
which can themselves be sensitive. There is no automatic public leaderboard.

## Where it fits

| Project | Responsibility |
| --- | --- |
| Keel | Coding-agent harness and tool execution |
| Keel Arena | Evaluation protocol, normalized evidence and comparisons |
| LLM-lab or another private consumer | Training-data selection, post-training and model artifacts |

A private consumer can use the versioned result contract to locate verified
training-split trajectories in its own artifact store. Arena does not automatically
turn failures into preference pairs or export evaluation tasks into training.

The [competitive research](docs/competitive-research.md) records the mechanisms
selected from Harbor, SWE-bench, Inspect and Aider.

See the [protocol](docs/protocol.md), [result contract](docs/results-v1.md),
[downstream interface](docs/downstream.md), and [execution roadmap](docs/execution.md).

## Contribute

MIT licensed. See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md).
Every commit and PR is public. Only original public source and synthetic fixtures
belong here. Publication checks are heuristic safeguards and still require human
diff review. No private repository history was imported.
