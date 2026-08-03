# Step 4.3 Evidence: Bounded-Retry Orchestrator

**Date:** 2026-06-12  
**Status:** COMPLETED  
**OpenSpec change:** `toolkit-accurate-ingest-llm-builder-final-editor`  
**Task:** 4.3 - Add one bounded retry to the final editor when validation fails with repairable diagnostics.

## Objective

Implement a high-level final-reconciliation orchestration helper that calls the final editor, applies/schema-validates/gates the patch, and performs at most one retry when validation diagnostics are repairable. Do not persist final reports yet.

## Implementation Summary

### `utils/toolkit_llm_final_reconciliation.py`

- 1 new constant: `MAX_FINAL_RECONCILIATION_RETRIES = 1`.
- 4 new orchestrator status names: `ACCEPTED`, `REJECTED`, `NOT_RETRYABLE`, `INVALID_BRIEF`.
- 2 new diagnostic codes: `RETRY_NOT_REPAIRABLE`, `RETRY_BUDGET_EXHAUSTED`. Reused existing failure codes for the underlying failure classes.
- Pure helper `_select_mock_provider_output_for_attempt(mock_provider_outputs, attempt_index)` for test-only plumbing. Returns the runner's `mock_provider_output` for the given attempt: `None` for the live provider, an indexed entry for a list/tuple, or the last entry when out of range. Empty lists collapse to `None` (live provider).
- Pure helper `_is_repairable_final_reconciliation_failure(apply_validate_gate_result) -> bool`. The helper returns `True` only when the apply phase produced `applied` AND the schema-validation phase reported `fail` or `error` (the only retryable class per the spec). All other failure classes return `False`.
- Pure helper `_build_final_reconciliation_retry_brief(brief, previous_diagnostics, attempt_index) -> dict`. Deep-copies the input brief and appends a `retry_context = {attempt_index, previous_diagnostics}` field. Never mutates the input; handles non-dict inputs by returning an empty dict.
- Pure helper `_summarize_attempt_for_orchestrator(attempt_index, runner_result, apply_validate_gate_result) -> dict` that produces a stable 5-key attempt record.
- Public orchestrator `run_final_reconciliation_with_bounded_retry(brief, module_dir=None, *, mock_provider_outputs=None, source="toolkit") -> dict` with the 8-step contract documented in `tasks.md`. Stable 8-key result shape.

### `scripts/test_toolkit_llm_final_reconciliation.py`

- 2 new constants in the import list (`MAX_FINAL_RECONCILIATION_RETRIES`, 4 orchestrator status names, 2 new diagnostic codes, 3 new private helpers, and the new public orchestrator function).
- 2 Step 4.3 fixtures: `_STEP42_APPLIED`, `_step42_schema_fail_result()`, `_step42_apply_failed_result()`.
- 10 new test classes with 57 new tests (all provider-free).

## Behavior Coverage

- No retry when attempt 0 succeeds through gates. `TestStep43NoRetryOnAttemptZeroAccepted` (2 tests).
- One retry when attempt 0 schema validation fails repairably and attempt 1 succeeds. `TestStep43RetryOnRepairableSchemaFailure.test_one_retry_when_attempt_zero_schema_fails_and_retry_accepted`.
- Exactly one retry max when both attempts fail repairably. `TestStep43RetryOnRepairableSchemaFailure.test_exactly_one_retry_max_when_both_attempts_fail_repairably`.
- No retry for invalid JSON / missing required keys / forbidden target / false source-fidelity / provider failure / refused reconciliation. `TestStep43NoRetryForNonRepairableFailures` (7 tests).
- Retry brief contains compact diagnostics and original brief remains unchanged. `TestStep43RetryBriefShape` (3 tests).
- `mock_provider_outputs` index selection: attempt 0 uses first output, retry uses second output. `TestStep43MockProviderOutputsPlumbing.test_mock_provider_outputs_index_selection`.
- No live provider calls when mock outputs are supplied. `TestStep43MockProviderOutputsPlumbing.test_no_live_provider_calls_when_mock_outputs_supplied`.

## Verification

```
.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py
```
-> PASS

```
.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v
```
-> **484 PASS, 0 FAIL** in 0.097s (was 427, +57 new tests)

```
.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety
```
-> **106/106 OK** in 0.086s (Step 1.4 regression set + dependent suites, no regression)

```
python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py
```
-> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`

```
openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict
```
-> VALID

```
openspec validate --specs
```
-> 364/364 PASS (no spec regression)

## Scope Confirmation

- No live provider in tests: the new tests use only `unittest.mock.patch` for `run_llm_final_editor` and `apply_validate_and_gate_final_reconciliation_patch_plan`. The `create_chat_client` mock is verified never called when `mock_provider_outputs` is supplied.
- No packet-builder integration: the orchestrator does not call or import any packet-builder helpers. Only the runner, the apply/validate/gate helper, and pure functions are wired.
- No report persistence: the orchestrator does not call any `safe_write_json` or `persist_*` helper. Report persistence is owned by Step 4.4.
- Max one retry: the orchestrator's `for attempt_index in (0, 1):` loop caps the total attempts at two. `MAX_FINAL_RECONCILIATION_RETRIES = 1` is the source of truth, exported and pinned by `TestStep43Constants.test_max_retries_value`.
