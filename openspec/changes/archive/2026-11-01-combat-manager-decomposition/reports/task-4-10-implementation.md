# Task 4.10 - Bounded Encounter HP Ledger Evidence

Status: provider-free implementation and focused verification complete. The
primary-owned `233336` review remains BLOCKED pending fresh primary-owned live
evidence; no live rerun or G3 PASS is claimed.

## Implementation boundary

- `process_combat_action_batch` captures a bounded HP projection from its
  already-loaded `encounter_data` only when the existing trace gate is enabled,
  before calling the existing updater. The updater call arguments and order are
  unchanged. A second bounded projection uses the canonical object returned by
  that same updater call and labels it `returned_persisted_state`; the first is
  labelled `preloaded_context`.
- Projection fields are flat writer-safe scalars: compact JSON strings for
  `hp_before`/`hp_after`, status, row count, truncation flag and source. The
  helper caps identities at 40 characters, rows at 12 and serialized projection
  bytes at 480. Missing/malformed/nonfinite/nonintegral/duplicate/long actor
  identities and row/byte truncation produce incomplete evidence; no HP or
  identity defaults are substituted. Metadata projection errors are contained
  and cannot prevent or change the updater outcome.
- Trace-off execution skips projection construction. The trace-off regression
  asserts the helper is not called, the context is unchanged, no extra I/O
  occurs under write guards, and the updater callback still runs once.
- The checker clears only the `ops: null` encounter-operation blocker when the
  event is uniquely positioned in one step, is the only encounter write in
  that step, targets the canonical selected encounter, and contains complete
  paired projections with the required provenance that exactly match canonical
  pre-step encounter HP and each other. This deliberately blocks sequences with
  ambiguous same-step encounter writes instead of inferring order. All other
  missing, invalid, nonzero, mismatched, duplicate, unknown-target or
  provenance-mismatched evidence remains blocked. Failed apply remains FAIL;
  unexplained canonical mutations remain FAIL. Structured character writes,
  exact mirror accounting and deterministic PC damage remain independently
  reconciled; no expectation is derived from prose or observed deltas.

## Focused evidence

All commands used `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`, project-local
`TMPDIR=tmp`, `PYTHONPYCACHEPREFIX=tmp/pycache`, and the repository venv. Each
unittest suite ran in a separate Python process.

| Suite / check | Result |
|---|---:|
| `scripts.test_combat_persistence_phase_stages` | 12 passed |
| `scripts.test_combat_trace_observation_writer` | 3 passed |
| `scripts.test_capture_drive` | 48 passed |
| `scripts.test_combat_latency_baseline` | 24 passed |
| `scripts.test_combat_validation_stage` | 15 passed |
| `scripts.test_combat_decomposition_contract` | 9 passed |
| `scripts.test_combat_resume_replay_guards` | 7 passed |
| `scripts.test_update_encounter_ops_runtime` | 4 passed |
| `scripts.c5_regression_combat` | 59 passed |
| `scripts.test_multi_pc_combat` | 73 passed |
| `scripts.test_combat_structured_ops_contract` | 16 passed |
| `scripts.test_combat_phase_integrity_precheck` | 23 passed |
| `scripts.test_combat_narration` | 13 passed |

The integration regression invokes the real `process_combat_action_batch` and
character persistence callback with function fakes, writes observations through
the real JSONL trace writer, parses source positions with the actual trace
parser, and runs actual `observed_checks`. It verifies a zero-HP encounter
metadata update whose fake updater mutates its input, subsequent structured HP
updates for Acheron and Blairen with canonical character/encounter mirrors, and
separate deterministic PC damage to Goblin. Negative evidence covers nonzero,
absent, invalid, duplicate, provenance-mismatched, target-incomplete and
failed-apply projections/outcomes without clearing the blocker or failure.
Existing Capture_Arena tests retain 1-PC/4-PC party-shape and HP causal-ledger
coverage.

Primary fresh software-only verification passed 306 tests in 13 separate
processes across the suites listed above. `py_compile` passed for both
implementation files and both focused test files. The AST audit found 265
combat-package functions, none over 600 lines; the compatibility shim is 17
lines. ASCII compliance scanned 1,135 files with zero violations. Strict
OpenSpec validation and scoped whitespace/diff checks passed after the final
report was added.

## Guard and evidence status

No live server, provider/API call, sandbox preparation, full owner loop,
campaign/key access, goal operation, Git mutation, or primary evidence rewrite
was performed. Test logs and Python cache output use project-local `tmp/`.
The corrected primary review identifies the initial Blairen character-prose
hypothesis as incorrect: the remaining blocker is the successful encounter
apply with `ops: null` and depth-truncated returned state. The raw review and
its initial hypothesis remain retained and unchanged. Fresh affected
primary-owned live evidence is still required; Tasks 5.3 and 5.4 remain
unchecked.
