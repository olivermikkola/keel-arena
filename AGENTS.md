# Working in Keel Arena

Read README.md and docs/protocol.md before implementation. Inspect branch and
working tree. Preserve other agents' work. Use independent PRs from current main.

## Scope and evidence

- Arena benchmarks coding agents. Keep training, model weights, and adaptation
  recipes in downstream repositories. Keep Keel's harness implementation in Keel.
- Prefer established sandbox/execution backends over another orchestration engine.
- Separate solved, unsolved, timed out, and infrastructure-error outcomes.
- Protect verifier inputs from agents; parsed calls and patches are not success.
- Match complete task/repetition blocks and pin provenance before comparing.
- Label synthetic demonstrations; never present them as model measurements.
- Freeze evaluation tasks separately from training; never automatically export
  held-out failures into training data.

## Public from the first commit

- Every commit and PR is public. Never copy private repository history, session
  logs, account identifiers, endpoints, credentials, private tasks or run artifacts.
- Keep private data outside this checkout, or in ignored private/ and runs/.
  Gitignore is not a redactor. Do not force-add ignored artifacts.
- Run scripts/check_publication.py against tracked files before every push.
  Review staged diff and paths. Publication checks are heuristic, not a guarantee.
- Add deliberate public fixtures only under examples/ and tests/. Review their
  provenance. New public paths require updating the publication allowlist.
- No automatic uploads, telemetry, model calls, Docker builds, or training in CI.

## Verification

Run python -m unittest discover -s tests -v, the documented CLI demonstration,
and the publication check. Include actual command output under ## Proof in PRs.
Only merge after required checks on the latest commit have run and passed.

Keep local work light. Use scratch under the user's home, never /tmp for builds,
clones, proof artifacts or browser profiles. Stop sustained work near 65-70 C.
Do not change services, keys or running model servers, or incur paid API costs.
