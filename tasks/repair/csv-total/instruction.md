Repair `/workspace/main.py`, a CSV invoice totaler. It reads a JSON object
`{"csv": "..."}` from stdin. The CSV starts with the exact header
`item,quantity,unit_cents`. Each subsequent record has exactly three fields.
`quantity` and `unit_cents` must consist of one or more ASCII digits; quoted CSV
fields and quoted commas in item names must work. Sum quantity * unit_cents for
all records using exact integer arithmetic. The header alone is valid with total 0.

Valid input produces `{"ok": true, "total_cents": N}`. Invalid CSV, bad headers,
incorrect field counts, noninteger/negative amounts, or an input object with
missing/extra keys must produce `{"ok": false}`. Blank records are invalid.

Keep the stdin/stdout JSON CLI and use only Python's standard library. Edit only
`main.py`; do not install dependencies. Final verification is separate.
