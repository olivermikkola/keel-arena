Read `/workspace/architecture_notes.txt` and write `/workspace/brief.md` obeying ALL 7 stacked constraints:
1. Exactly these 4 H2 headings in order: `## Summary`, `## Architecture`, `## Constraints`, `## Checklist`.
2. `## Summary` body text must contain strictly between 25 and 45 words (inclusive).
3. Forbidden words (case-insensitive) anywhere in file: `cloud`, `unlimited`, `magic`, `todo`, `tbd`.
4. `## Checklist` must contain exactly 4 bullet lines starting with `- `, sorted alphabetically (case-insensitive).
5. Must mention the exact port `8443` and exact RAM cap `512MB` from `architecture_notes.txt`.
6. The final block of the file must be a fenced ```json code block containing `{"owner": "edge-team", "port": 8443, "ready": true}`.
7. No line may have trailing spaces.
