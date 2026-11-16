Correlate `/workspace/incidents/metrics.csv` and `/workspace/incidents/deploy_log.jsonl` following `/workspace/incidents/runbook.md`.
1. Write `/workspace/postmortem.json` with exact keys:
`{"affected_service": str, "faulty_commit": str, "peak_error_rate_pct": float, "rollback_commit": str}`
2. Write `/workspace/postmortem.md` containing a concise root-cause narrative and concrete action items (evaluated by both structural checks and Frontier LLM rubric).
