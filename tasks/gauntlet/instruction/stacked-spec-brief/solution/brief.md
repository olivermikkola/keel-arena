## Summary

Keel Edge Gateway terminates local TLS 1.3 traffic on port 8443 within a strict 512MB memory cap, persisting requests to an append-only SQLite WAL store for reliable offline-first edge deployments.

## Architecture

The gateway listens on port 8443 with TLS 1.3 enabled and writes session state to local SQLite WAL storage.

## Constraints

Memory usage is capped at 512MB RSS on local edge nodes owned by edge-team.

## Checklist

- Confirm 512MB memory limit
- Enable SQLite WAL mode
- Enforce TLS 1.3 cipher suite
- Verify port 8443 listener

```json
{"owner": "edge-team", "port": 8443, "ready": true}
```
