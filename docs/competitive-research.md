# Competitive research and implementation choices

Reviewed 2026-11-15. These are design adaptations, not copied implementations or
claims that Arena matches these projects' benchmark coverage.

| Project | Useful mechanism | Arena decision |
| --- | --- | --- |
| Harbor | Installed-agent adapters, separate verifier environments, trial artifacts, ATIF | Integrate the existing engine; keep model execution out of the reporting CLI. Pin 0.26.0, validate its actual SDK, and retain native evidence. |
| SWE-bench | Grade final patches against protected repository tests; explicit broken/fixed controls | Test task verifiers with broken, repaired and adversarial submissions before trusting a model score. Use content hashes and fresh run directories; never reuse a cached score for a changed patch. |
| Inspect | Detailed evaluation logs, error policies, repeated epochs and clustered metrics | Keep infrastructure errors distinct, preserve unknown usage, and compare paired tasks. Repetitions are not independent tasks. Add task-clustered uncertainty before interpreting leaderboard differences. |
| Aider | End-to-end editing measured by actual unit-test outcomes | Measure completed edits and repair loops, not whether a tool call parses. Small tasks diagnose specific failures; they cannot establish general coding ability. |

## Deliberate differences

Arena's public repository ships tooling and original public task definitions.
Private users retain endpoints, logs, artifacts and training datasets locally.
There is no upload hook or training service. Public task solutions are unsuitable
as a blind holdout; fresh private task banks remain necessary.

A backend adapter and an importer form separate layers. The adapter runs a pinned
Keel binary inside a backend task environment. The importer verifies a complete
predeclared attempt matrix and explicit bindings before producing Arena results.
Never infer contestant identity or repetition numbers from directory-name suffixes.
A successful backend process without a valid protected reward is not a solve.

## Sources

- [Harbor custom agents](https://docs.harborframework.com/agents/custom-agents)
- [Harbor separate-verifier configuration](https://docs.harborframework.com/tasks/configuration#verifier)
- [Harbor ATIF](https://docs.harborframework.com/agents/atif)
- [Pinned Harbor source, Apache-2.0](https://github.com/harbor-framework/harbor/tree/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4)
- [SWE-bench harness and cache behavior](https://www.swebench.com/SWE-bench/reference/harness/)
- [Inspect logs and retry provenance](https://inspect.aisi.org.uk/eval-logs.html)
- [Inspect clustered metrics](https://inspect.aisi.org.uk/metrics.html)
- [Aider end-to-end benchmark methodology](https://aider.chat/docs/benchmarks.html)

No third-party source or dataset is vendored. Any future reuse must preserve the
upstream license and attribution; techniques are reimplemented for Arena's needs.
