Invoke `python3 /workspace/service.py` to fetch all paginated metric items and reconcile them into `/workspace/summary.json`.
`service.py` enforces strict pagination and token rules and returns JSON error hints when called incorrectly.
Write `/workspace/summary.json` with exact keys:
`{"item_ids": [sorted list of all string ids], "sum_values": int}`
