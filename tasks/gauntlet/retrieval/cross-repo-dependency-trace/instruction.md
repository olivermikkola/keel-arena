Inspect `/workspace/traces/shard_01.txt` .. `shard_10.txt` to trace the active call chain from `gateway` to `ledger-db`.
Identify the active ordered path, the single deprecated hop, and the offline decoy node.
Write `/workspace/trace_report.json` with exact keys:
`{"active_path": [list of node strings], "deprecated_hop": str, "offline_node": str}`
