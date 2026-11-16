## Findings

1. [HIGH] SQL injection in `get_user`: string interpolation allows arbitrary SQL; restore parameterized `?` binding.
2. [MEDIUM] File descriptor leak in `read_audit`: `open(path)` is never closed; restore the `with open(...)` context manager.
3. [MEDIUM] Off-by-one bug in `paginate`: `start + size + 1` returns one extra item per page; use `start + size`.

## Verdict

REQUEST_CHANGES
