# Execution roadmap

## Decision: use an established sandbox backend

Arena validates/imports backend results and supplies a Keel installed-agent adapter.
Harbor owns task environments, scheduling and verification. A small wrapper inside
the task sandbox enforces request/output budgets and records provider evidence.
See [adapter usage and its evidence limits](keel-agent.md).

Harbor is the first backend to integrate. Its documentation recommends an
installed-agent adapter when the agent CLI belongs inside the task environment.
The SDK dependency is pinned and contract-tested; the wrapper has a real Keel
scripted-provider execution proof. A full backend/model benchmark remains to run. See [Harbor's custom-agent interface](https://docs.harborframework.com/agents/custom-agents).
This does not claim that container isolation or model quality has been verified.

## Next milestones

1. Pin Harbor, a public Keel executable/build and a tiny original task pack.
   Verify environment startup and reference broken/fixed behavior. Keep verifier
   inputs, solutions, host home and other attempts inaccessible to the agent.
2. Implement a Keel installed-agent adapter and normalize backend results to v1.
   Enforce actual context, step, output and wall-clock budgets. Record observed
   settings and immutable evidence. Distinguish model timeouts from backend faults.
3. Run a small matched model comparison with repetitions. Archive raw evidence
   privately; report task coverage, failures, cost/time and complementary solves.
4. Expand only after the comparison can guide a concrete model or harness choice.
   A private consumer can then study post-training on a disjoint training bank.

No backend, model, Docker daemon or existing service was installed or started to
bootstrap this repository. Local reporting tests do not validate sandbox security,
provider behavior, coding quality or post-training gains.
