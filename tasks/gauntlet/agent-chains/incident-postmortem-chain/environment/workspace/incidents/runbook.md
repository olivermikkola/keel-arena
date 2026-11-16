# Incident Runbook
1. Find the minute where `error_rate_pct` spiked above 5.0.
2. Match that timestamp window in `deploy_log.jsonl` to identify the deploy commit that preceded the spike.
3. Record the rollback commit that restored normal rates.
