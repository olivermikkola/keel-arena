# Contributing

Read AGENTS.md and the protocol. Keep PRs focused and based on current main.

```sh
python3 -m unittest discover -s tests -v
python3 -m keel_arena validate examples/synthetic-results.json
python3 -m keel_arena report examples/synthetic-results.json
git add <reviewed-public-files>
python3 scripts/check_publication.py
git diff --cached --check
git diff --cached
```

The publication check audits both index and working bytes of tracked files. It
uses a small path/type allowlist and common secret/private-location patterns;
it is not comprehensive secret detection or a redactor. It does not scan prior
history. Review every commit before pushing; CI cannot undo public exposure.
Never force-add private artifacts. Add only deliberately reviewed public source
and synthetic fixtures to the allowlist when needed.

Document real invocations under ## Proof in PRs. Tests must exercise meaningful
behavior, not merely repeat constants. Routine CI must remain cheap and offline;
no model inference, paid API calls, training or heavyweight container builds.
