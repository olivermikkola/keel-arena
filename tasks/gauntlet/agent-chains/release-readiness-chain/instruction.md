Complete the multi-step release verification workflow in `/workspace`:
1. Inspect `changelogs/v2.4.md`, `manifests/services.json`, and `deploy/target.env`.
2. Run `python3 /workspace/checks/verify_deps.py` to discover version/config mismatches.
3. Reconcile `manifests/services.json` and `deploy/target.env` to match `changelogs/v2.4.md` (which is authoritative!).
4. Re-run `python3 /workspace/checks/verify_deps.py` until it exits 0, then write `/workspace/release_bundle.json` with exact keys:
`{"release": "2.4.0", "services": {"auth": "2.4.0", "billing": "2.4.1"}, "checks_passed": true}`
