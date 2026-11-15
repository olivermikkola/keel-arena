# Private ATIF trajectories

Keel Arena records complete native provider requests and responses privately. Its
Harbor adapter can now export a text-only execution timeline using Harbor's
**ATIF-v1.8** schema. It writes `agent/trajectory.json` during post-run context
collection and links its byte digest in the normalized attempt result. Existing
native evidence stays authoritative and is never replaced.

You can also explicitly convert an earlier recorded agent directory offline:

```sh
python3 -m keel_arena export-trace "$PRIVATE_AGENT_DIRECTORY" --out "$NEW_PRIVATE_TRACE_FILE"
```

This requires the pinned `harbor==0.26.0` extra for upstream schema validation.
It makes no model calls, executes no task code, and uploads nothing. The output
must be new and uses mode 600. It includes private prompts, model output, tool
arguments, observations and model identifiers; it is not a public/redacted export.

## Evidence fidelity

- Each agent step links to the exact native completion file and its byte digest,
  plus the canonical request digest. Native records preserve the full actual
  context, tools and response, including context changes between calls.
- Initial text messages and observed model responses are preserved. Token counts
  come from provider responses and runtime accounting, with unknown values left
  unknown. Known aggregate counts must agree with the native ledger.
- Native tool IDs are scoped by request number to avoid collisions when a small
  model reuses an ID. The original ID stays in `extra.native_tool_call_id`.
- Tool observations are attached only when they occur in the new suffix of the
  next request after an unchanged prior context. A rewritten context might carry
  an older receipt with a reused ID; the exporter leaves that observation missing
  rather than claim it belongs to the new action. Missing IDs are listed explicitly.
- Incomplete request ledgers, malformed arguments, symlinked evidence, unsupported
  multimodal/history shapes and ambiguous observations fail closed. Raw evidence
  remains available for diagnosis or future converters. No synthetic receipt is
  generated from a requested action.

ATIF is an execution timeline, not a tokenizer-ready SFT sequence. For training,
use the linked native request as the exact conditioning context for its response;
do not reconstruct it by concatenating ATIF steps across compaction. A valid ATIF
file does not establish task success, data permission or holdout eligibility.

## Scoring and downstream consumers

Trace conversion is separate from task grading. If conversion fails, the adapter
records `arena_trace_export_error` and the importer withholds the trajectory
pointer, including any stale file, while retaining the independently verified
solve outcome. A failed conversion must not remove a hard task from comparisons.

A private consumer can join the trajectory and verifier-result digests to its own
artifact store. It must verify bytes, task success, split/provenance and licensing
before selecting any training example. This feature does not export SFT/DPO pairs,
train weights or move evaluation failures into training. See
[the downstream boundary](downstream.md).

The converter is tested against the real pinned Harbor schema and validator. An
offline conversion of the actual Keel scripted-provider execution produced a valid
four-step timeline with two model requests, one replayed tool observation and no
missing observation IDs. This is real harness evidence with a scripted provider,
not a measured language-model capability result.
