Convert `/workspace/legacy.ini` into strict JSON `/workspace/migrated.json` matching `/workspace/schema_notes.md`:
- `port`: integer `1..65535` (from `server.port`)
- `tls`: boolean `true`/`false` (from `server.tls`; `"yes"`/`"true"` -> `true`, `"no"`/`"false"` -> `false`)
- `allowed_origins`: sorted list of valid `https://` URLs from comma-separated `security.origins` (drop any `http://` or blank items, recording dropped entries in `rejected_origins`)
- Exact top-level keys: `{"allowed_origins": [...], "port": int, "rejected_origins": [...], "tls": bool}`
