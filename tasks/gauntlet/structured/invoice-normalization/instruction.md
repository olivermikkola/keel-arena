Normalize `/workspace/raw_invoices.csv` into `/workspace/normalized.json`.
Rules:
- CSV contains quoted fields (`"Acme, Inc."`) and duplicate `invoice_id` rows; keep the row with the latest ISO `updated_at` timestamp for each `invoice_id`.
- Parse `amount` (`$12.50`, `USD 12.50`, `12.50`) into integer `amount_cents`.
- Any row with negative amount or non-USD currency (e.g. `EUR`) must be excluded from `valid` and its `invoice_id` placed in `rejected_ids` (sorted).
- `valid` must be sorted ascending by `invoice_id`, with exact keys `invoice_id`, `vendor`, `amount_cents`, `updated_at`.
