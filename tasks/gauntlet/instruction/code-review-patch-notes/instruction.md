Review `/workspace/diff.patch` and write `/workspace/review.md`.
Requirements:
1. Include exact H2 headings: `## Findings` and `## Verdict`.
2. Identify all 3 distinct defects in the patch (SQL injection, unclosed file handle leak, off-by-one pagination slice).
3. Under `## Findings`, format each finding as a numbered item (`1. `, `2. `, `3. `) mentioning severity (`HIGH` or `MEDIUM`).
4. Under `## Verdict`, state `REQUEST_CHANGES` on its own line.
5. Total length must be <= 220 words.
