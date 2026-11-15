# Freeze and run private studies

Arena can plan and execute a complete matched task/model/repetition matrix using
Harbor 0.26.0. This is an explicit execution command, unlike offline `report`,
`validate` and `import-harbor`. It runs trusted task images, grading code and your
privately supplied Keel binary. Review configurations and task packs first.
The initial runner supports local Linux/Docker and separate single-step verifiers;
no paid/cloud backend is selected automatically.

Install `.[harbor]`, Docker Compose and Buildx. Copy
`examples/study-template.json` **outside Git** and replace its placeholders with
private paths, an executable digest, model IDs/endpoints and immutable model
manifest digests. Add contestants to compare more than one model. Each task key
must match its Harbor task name and be a simple identifier. Relative paths resolve
from the current working directory. The template intentionally cannot run without
real identities; it is not measured model data.

```sh
HARBOR_TELEMETRY=0 python3 -m keel_arena freeze-study "$PRIVATE_STUDY_CONFIG" --out "$NEW_PRIVATE_STUDY_DIRECTORY"
HARBOR_TELEMETRY=0 python3 -m keel_arena run-study "$NEW_PRIVATE_STUDY_DIRECTORY"
python3 -m keel_arena report "$NEW_PRIVATE_STUDY_DIRECTORY/results.json"
```

## What freeze commits

Freeze resolves the exact serialized Harbor configs, attempt order, task and
verifier bytes/permissions, native task checksums, Keel executable digest, Arena
execution implementation and shared sampling/budget policy. It writes a private
`frozen.json`, content-hashed `receipt.json` and initial `state.json`. It creates
no trial, sandbox or model request. Output must be a new directory; its mode is
700, and JSON documents use mode 600.

The model revision digest identifies an operator-supplied immutable manifest,
including weights/tokenizer or provider revision and quantization. Arena verifies
the declared identity and config bindings; it cannot cryptographically attest a
remote provider's weights. Preserve the model manifest and server provenance
privately. Never fill that field with an arbitrary number and call it verified.

`max_steps` means upstream model requests for this adapter, not individual tool
calls. Output cap, context setting, sampler and timeout follow the
[adapter contract](keel-agent.md). Seeds use `base seed + repetition` for every
contestant in a matched block. Contestant order rotates per task/repetition;
execution is serial. There are no implicit infrastructure retries or replacements.

Select an API credential by **environment variable name**, never by value.
`api_key_env: null` explicitly selects anonymous access and prevents fallback to
unrelated ambient provider keys. A named variable must be present at execution.
Allowed agent hosts must include reachable provider hosts; the separate verifier
remains offline for the supplied task pack. Each study has a unique backend namespace so separate study directories cannot
collide through generic Docker project names.

No credentials, endpoints, native logs
or private study files are uploaded by Arena.

## Execution, interruption and resume

Run checks the frozen receipt and source digests before execution and before each
new attempt. It refuses changed task/verifier/binary/Arena bytes or moved studies.
An OS file lock prevents concurrent execution of the same study and releases on
process exit. Trial lifecycle, artifact handling and teardown are delegated to
Harbor. Completed results are imported against their original bindings before
aggregation; backend exit status alone is never a solve.

A thermal policy is explicit: `thermal_limit_c` checks supported host CPU sensors
before and during each trial. Crossing the limit cancels the active trial and
awaits Harbor teardown. The stop and any completed/cancelled evidence remain
private; unfinished matrix cells are not fabricated as model failures. Choose
`null` explicitly only when no host thermal guard is needed. Beelink runs must
keep the 65–70 C operating rule; limits above 68 are rejected.

```sh
HARBOR_TELEMETRY=0 python3 -m keel_arena run-study "$PRIVATE_STUDY_DIRECTORY" --resume
```

Resume validates existing completed attempts instead of replaying them, including
infrastructure failures. A directory containing partial/missing evidence is
refused; preserve it and start a new study rather than overwrite it. There is no
silent retry of failed cells to improve the score. A thermal stop with valid
cancelled evidence can resume the remaining cells once the host is cool.

Only a complete matrix produces `results.json` and `report.json`. `state.json`
reports progress/stops, and all native evidence stays under `trials/`. Reports
still exclude whole infrastructure-failed blocks across contestants. A completed
study with zero matched blocks is not evidence of coding performance. Public
sharing requires a separate deliberate review; the public repository's ignore
rules are not a redactor.

Exit code 0 means command completion, 2 means invalid/unreadable input or a run
error, and 3 means a deliberate thermal stop. A completed matrix may still contain
model failures or excluded infrastructure outcomes; inspect the report, not only
the exit code. On cancellation, Arena drains Harbor's shielded environment stop
coroutines before returning, so a pending verifier-sidecar shutdown is not cut
short by the event loop closing.
