# Run Keel with Harbor

Arena supplies an installed-agent adapter for **Harbor 0.26.0**, using a local
user-provided Keel executable. No private source, binary or credentials are
published, downloaded or built by the adapter. The public project can therefore
be used with a privately built harness.

Install the optional extra in Python 3.12 or later. Set `HARBOR_TELEMETRY=0`
when launching Harbor if you want its optional usage telemetry disabled (Arena
itself sends no telemetry):

```sh
python3 -m pip install '.[harbor]'
```

Use `keel_arena.harbor_agent:KeelAgent` as Harbor's custom agent import path. The
adapter's required kwargs are `binary_path` (local path in the controller) and
`binary_sha256`. It checks the local digest, uploads the executable into the task
environment, and checks its remote digest even when installation is skipped.
`skip_install` requires the exact executable already baked into the task image.
The environment must provide Python 3.11+, POSIX shell, sha256sum, cut, the binary's
shared libraries, and writable `/installed-agent` and `/logs/agent` locations.
The adapter uses the task's declared working directory, or detects the image
working directory with `pwd`. An explicit absolute `workspace` kwarg can override it.

Configure the following kwargs using a private Harbor job file (real booleans,
not string values):

| Setting | Default | Meaning |
| --- | --- | --- |
| `max_model_requests` | 12 | Maximum upstream completion requests, including failed requests |
| `max_output_tokens` | 4096 | Forced per-request `max_tokens` |
| `context_tokens` | 16384 | Keel's context-management setting, not an exact tokenizer limit |
| `timeout_seconds` | 300 | Wrapper wall-clock limit including provider calls |
| `temperature` / `top_p` / `seed` | 0.0 / 1.0 / 0 | Forced sampler sent on every request |
| `thinking` | null | Server default; boolean explicitly sets `enable_thinking` for compatible servers |

Set Harbor's agent timeout slightly above `timeout_seconds + 10` to allow wrapper
cleanup; keep the wrapper timeout identical across contestants. Freeze this policy
and the task/image/Keel identities before running. Configure the private base URL
through Harbor's `--base-url` or model connection settings; API keys are resolved
through `KEEL_API_KEY` or `OPENAI_API_KEY` into a scoped environment. They never
appear in the subprocess command line or Arena's completion evidence. Provider
identifiers remain private in job files and native Harbor results.

## Why a bounded provider wrapper

The inspected Keel one-shot CLI uses a fixed internal agent-loop limit despite
accepting `--steps`; its provider request does not set a completion-token limit.
Arena therefore caps upstream requests itself and overrides sampling/output limits
rather than claiming those flags are enforced. A model request is not a tool call;
one completion can contain several actions. `max_steps` in an Arena plan for this
adapter means `max_model_requests` and must use the same declared value.

The wrapper requests **streaming** responses upstream, collects bounded SSE
and final usage, then serves the assembled SSE envelope to Keel. Providers that
ignore the streaming flag and return ordinary JSON remain supported. This avoids
holding upstream response headers until a full slow completion finishes, which
can exceed an intermediary's header deadline. It is still a collected transport,
not a live token-for-token relay, so freeze it consistently across contestants.

The exact raw SSE is retained privately as `stream-N.sse`; the assembled response
links its digest. Text, explicit reasoning, fragmented tool arguments and final
usage are reconstructed, while incomplete/error streams fail closed. Providers
must support OpenAI Chat Completions and declared sampler fields. Unsupported
parameters remain infrastructure errors. Model context/truncation and server-side
sampling compliance still require operator verification.

Each sandbox run creates fresh home and log directories. Logs contain private
request/response evidence, native Keel output, and `runtime.json` with request
counts, observed usage and termination reason. Each accepted request is saved
before the provider call, including requests that later fail. A failed call also
gets bounded private error evidence (HTTP status, exception type, up to 64 KiB
of error body). The configured API credential is redacted from that body;
request headers are never recorded. In-flight calls without a completed response
leave token usage unknown, including after a wall timeout. Typed context-window errors are
graded as agent outcomes; arbitrary error prose cannot change classification. No completion usage means unknown,
not zero. An agent that catches a rejected over-budget request and exits zero is
still a failed budget outcome. Wall timeout kills its process group. External
Harbor cancellations remain Harbor's responsibility.

The wrapper is a budget/accounting layer inside the backend environment, **not a
security sandbox**. It is not hardened against an agent attacking same-user
processes or reading arbitrary sandbox files. Use trusted task packs, Harbor's
network restrictions and a separate protected verifier. Never expose the host home,
Docker socket, task solutions, other attempts or verifier inputs to the agent.
`--yolo` permits task mutations inside that environment; Keel's own sandbox stays
enabled. MCP servers, skills injection, resume and native configuration overrides
are unsupported and must not be silently injected into comparisons.

The supplied task images use a digest-pinned Debian trixie Python base, which
supports the GLIBC 2.39 required by the inspected native Keel executable. The
previous bookworm base had GLIBC 2.36 and could pass grader-only controls while
failing to launch that executable. Other private binaries still need compatible
image libraries or a compatible build.

## Evidence and verification status

The adapter is tested against the real pinned Harbor SDK with a recording
execution environment. Runtime tests execute actual subprocesses and a local
scripted provider to check sampling overrides, request limits, timeouts, secret
forwarding and unknown usage. They do not establish backend isolation.

An opt-in smoke exercises an actual Keel binary, its `write_file` tool and
observation replay through the same wrapper, without model inference:

```sh
python3 scripts/smoke_keel.py --binary "$KEEL_BINARY" --out "$NEW_PRIVATE_PROOF_DIRECTORY"
```

The proof directory must be new. Keep it outside public Git. Passing this smoke
establishes integration, not coding quality. A real-model benchmark additionally
needs validated tasks, protected verification and real backend execution. No Docker
container or model generation was needed for this integration smoke.
