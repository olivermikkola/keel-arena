Use the local CLI tool `python3 /workspace/dbtool.py` to inspect the catalog and orders data (built from `seed.json`).
`dbtool.py` enforces strict query flags — read its error messages carefully if a call fails.
Compute total revenue (in integer cents: `qty * unit_cents`) across `completed` orders only, grouped by `category`, and identify the highest-revenue `sku`.
Write `/workspace/report.json` with exact keys:
`{"by_category_cents": {"books": int, "hardware": int}, "top_sku": str, "total_completed_cents": int}`
