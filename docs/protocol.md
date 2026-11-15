# Benchmark protocol

Arena compares models using the same pinned harness, task snapshots, protected
verifiers, sampling policy, and budgets. Model identity and quantization are
recorded per contestant. Repetitions are distinct attempts, not independent tasks.

A verifier must check the requested final state. Intermediate failed tests may be
part of a successful repair. Timeouts are unsolved outcomes; broken infrastructure
is a separate outcome. Preserve failures and raw evidence privately.

Public reporting requires an intentional review. Private task banks, model
endpoints, raw traces, patches and account data never belong in this repository.
