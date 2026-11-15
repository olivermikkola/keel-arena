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

## Verified so far

- Offline Harbor importer with exact config/task bindings and evidence checks.
- Pinned SDK contract tests, bounded wrapper subprocess tests, and actual Keel
  tool execution/observation replay against a scripted provider.
- [Original development task pack](task-pack.md), pinned image and content
  manifests, with real Harbor/Docker oracle and no-op grading controls.

## Remaining end-to-end work

1. Produce a frozen private study manifest and exact trial bindings through a
   convenient Arena command, using the established Harbor execution engine.
2. Preserve validated interchangeable trajectories alongside native evidence.
3. Run a small matched real-model comparison with repetitions and thermal/resource
   guards. Report task coverage, failures, usage and complementary solves.
4. Expand task/model coverage only after results can guide a concrete decision.
   Private consumers can study post-training on a disjoint training bank.

No model improvement is claimed. Grading controls and scripted-provider proofs
cannot establish real model coding quality. No existing service was restarted or
reconfigured for the development work.
