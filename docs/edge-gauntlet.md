# Edge Agentic Gauntlet & Hardware Profiling

Keel Arena extends its reproducible coding-agent harness with a **7-suite Edge Agentic Gauntlet** (`tasks/gauntlet/`) and hardware/inference telemetry (`keel_arena/edge.py`), combining the practical subagent focus of SLM Gauntlet with the long-horizon engineering, token-efficiency, and pairwise Elo dimensions highlighted by modern Qwen 4 / DeepSWE / Terminal-Bench / AgentArena evaluations.

## Suites (`tasks/suites.json`)

| Suite | Tasks | What it measures |
| --- | --- | --- |
| `coding` | `cli-pipeline-fix`, `terminal-log-indexer` (+ `repair`: `config-check`, `csv-total`) | Multi-file debugging, UTC/schema repair, greenfield CLI contracts |
| `tool-use` | `sqlite-query-repair`, `api-contract-recovery` | Recovering from tool error codes, pagination, strict CLI arguments |
| `adversarial` | `injected-issue-triage`, `misleading-hint-trap` | Prompt-injection resistance, fake system overrides, misleading debug notes |
| `agent-chains` | `release-readiness-chain`, `incident-postmortem-chain` | Multi-step cross-file workflows, verification loops, root-cause synthesis |
| `structured` | `invoice-normalization`, `config-migration-schema` | Quoted CSV normalization, typed JSON schema compliance, integer arithmetic |
| `retrieval` | `chronological-policy-override`, `cross-repo-dependency-trace` | Multi-doc chronological overrides, transitive dependency tracing, refusing absent facts |
| `instruction` | `stacked-spec-brief`, `code-review-patch-notes` | Stacked formatting/negative/word-count constraints + hybrid Frontier LLM rubric |

List all suites and tasks:

```sh
python3 -m keel_arena list-suites
```

## Hardware Auto-Detection & Inference Profiling

Detect host CPU, memory, accelerators (CUDA / Vulkan / AMDGPU), and thermal sensors:

```sh
python3 -m keel_arena probe-edge
```

Measure live local server TTFT and `1 -> N` stream decode throughput (`tok/s`) against an OpenAI-compatible or `llama-server` endpoint:

```sh
python3 -m keel_arena probe-edge --base-url http://127.0.0.1:8080/v1 --model my-slm --streams 1,4 --out edge-profile.json
```

## One-Command Study Initialization & Visual Scorecards

Initialize a `schema_version: 2` study config with auto-hashed `keel` binary and contestant specs (`name=model@base_url[|quant|harness|API_KEY_ENV]`):

```sh
python3 -m keel_arena init-study \
  --suite gauntlet \
  --contestant qwen-4b=openai/qwen4-4b@http://127.0.0.1:8080/v1\|Q4_K_M\|keel \
  --contestant bonsai-9b=openai/bonsai-9b@http://127.0.0.1:8081/v1\|Q2_0\|keel \
  --probe-edge \
  --out my-study.json
```

Generate shareable SLM-Gauntlet-style SVG scorecards (`overview.svg`, `card-<contestant>.svg`) and an offline interactive `dashboard.html` (with Pareto speed-vs-accuracy scatter plot, suite grid, and Elo table):

```sh
python3 -m keel_arena cards examples/synthetic-gauntlet-results.json --out ./demo-cards
python3 -m keel_arena report examples/synthetic-gauntlet-results.json --format html > ./demo-dashboard.html
```
