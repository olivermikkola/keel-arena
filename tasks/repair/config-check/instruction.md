Repair `/workspace/main.py`, a JSON configuration validator. It reads one JSON
value from stdin and writes one JSON result to stdout.

The input must be an object with exactly `workers` and `label`. `workers` must be
an integer from 1 through 16 inclusive. JSON booleans and floating-point numbers
are not integers for this interface. `label` must be a string with 1–12 ASCII
letters, digits or hyphens. Unknown/missing fields and malformed values must
produce `{"ok": false}`. Valid input produces `{"ok": true}`.

Preserve the CLI interface and standard-library-only implementation. Edit only
`main.py`. Do not install dependencies. You may run local checks yourself; final
verification uses a separate environment and additional cases.
