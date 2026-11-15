# Original repair task pack

`tasks/repair/` is an original MIT-licensed **development diagnostic pack**, not a
blind holdout or a claim of broad coding coverage. It contains two actual CLI
repair tasks, with 43 protected grading cases total:

| Task | Repeated failure it diagnoses | Cases |
| --- | --- | --- |
| `config-check` | Python bool/int confusion, inclusive bounds and exact configuration shape | 23 |
| `csv-total` | CSV quoting/newlines, ASCII integer validation and exact money arithmetic | 20 |

Each task is a standard Harbor 1.4 task with an instruction, a digest-pinned Python
image, broken source in the environment build context, a separate verifier, and a
reference repair in `solution/`. Only `environment/` is the image build context;
reference solutions and grading code are not in the agent image. Only `main.py`
is transported as an artifact to the separate verifier. The grader checks the
requested CLI behavior with controller-side expectations; tool syntax and a
printed “passed” message do not satisfy it.

The controller never imports candidate code. It executes each candidate as UID/GID
65534 with no supplementary groups or provider environment, Python isolated mode,
a one-second per-case wall limit and CPU/memory/file-output limits. `/tests` and
`/logs/verifier` are root-only; the candidate cannot overwrite grading code or its
reward file. Grading fails closed unless it can drop privileges from root. The
verifier always writes the final binary reward itself. This reduces same-process
test tampering; it is not a complete audit of Harbor/Docker containment.

The base image is pinned to an official registry manifest digest. Both the agent
and verifier start with networking disabled; the agent phase is explicitly an
allowlist with no allowed hosts until the caller supplies its provider host using
Harbor's `--allow-agent-host`. The verifier remains offline. Use only trusted
endpoint/task configurations and never expose credentials in shell arguments.

## Run controls before benchmarking

Install Harbor with the optional extra. Docker must have Compose and Buildx.
Use new private job directories and one concurrent environment:

```sh
HARBOR_TELEMETRY=0 harbor run -p tasks/repair/config-check -a oracle -n 1 --max-retries 0 --jobs-dir "$PRIVATE_JOBS" --job-name config-oracle
HARBOR_TELEMETRY=0 harbor run -p tasks/repair/config-check -a nop -n 1 --max-retries 0 --jobs-dir "$PRIVATE_JOBS" --job-name config-broken
```

Repeat for `csv-total`. The oracle must get reward 1; the no-op must get reward 0.
Inspect per-trial `exception_info` and verifier evidence: Harbor can exit zero
while its trials contain infrastructure errors. An exception is not a failed
model score. Preserve failed attempts; never reuse a job name after changing a
candidate. Once these controls pass, use the [Keel adapter](keel-agent.md) instead
of `oracle`, with your private binary, immutable model identity and provider host.

Ordinary CI checks task schemas against the pinned SDK and executes the original
broken/fixed/forged controls using unprivileged local subprocesses. Those local
checks deliberately do not claim protected UID separation or Docker execution.
No Docker builds or model calls run on normal pushes/PRs.

These public tasks and solutions must not be treated as unseen-model evaluation.
Keep final evaluation repositories and derivative tasks out of training data.

## Verified backend controls

On 2026-11-15, Harbor 0.26.0 ran the following controls with actual Docker
containers and separate offline verifier environments. Every trial had no
`exception_info` and `reward_valid: true`:

| Task | Reference repair (`oracle`) | Untouched broken source (`nop`) |
| --- | --- | --- |
| `config-check` | 1, 23/23 cases | 0 |
| `csv-total` | 1, 20/20 cases | 0 |

This validates these task environments and grading controls. It is not a model
score, a complete containment audit, or a general coding benchmark result.
Earlier local attempts failed before container execution because Buildx was
missing and the isolated Docker configuration initially lacked Compose. Those
failed artifacts were preserved. Final controls used a checksum-verified,
task-local Buildx 0.39.0 and the existing Compose 5.5.0 plugin, without modifying
the Docker service or system configuration. All trial containers stopped afterward.
