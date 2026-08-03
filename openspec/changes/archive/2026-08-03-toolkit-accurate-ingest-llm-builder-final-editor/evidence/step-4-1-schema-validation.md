# Step 4.1 Evidence: Schema Validation After Patch Application

Date: 2026-06-12

## 1. Files Added

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-4-1-schema-validation.md` (this file)

## 2. Files Modified

- `utils/toolkit_llm_final_reconciliation.py`
  - Defensive import of `ModuleValidator` from `core.validation.validate_module_files`. When the package is unavailable the constant is set to `None` so the helper degrades to a structured error instead of crashing.
  - Module-internal `_TOOLKIT_FINAL_RECONCILIATION_REPO_ROOT` constant resolved from `Path(__file__).resolve().parents[1]`. Used to anchor the `ModuleValidator` schema dir the same way `scripts/test_toolkit_homebrew_readiness_gate.py` does.
  - 4 new stable status constants: `FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS`, `_FAIL`, `_ERROR`, `_NOT_RUN`.
  - 2 new diagnostic codes: `DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED`, `DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR`.
  - 1 new pure helper: `_parse_validator_error_message(raw_message) -> (file, message)` for best-effort splitting of ModuleValidator's heterogeneous error string shapes. Never raises; never mutates.
  - 1 new pure helper: `collect_schema_validation_results(validator_results) -> dict` for collapsing `ModuleValidator.results` into the compact shape `{status, success_rate, passed, failed, errors: [{category, file, message}, ...]}`. Pure; never includes raw `files` lists; skips legacy scalar category payloads; handles non-dict inputs gracefully.
  - 1 new public function: `run_final_reconciliation_schema_validation(module_dir) -> dict` that instantiates `ModuleValidator(module_dir, repo_root)`, calls `execute_full_validation(verbose=False)`, routes through the collector, and returns the structured shape. Fail-closed on three failure classes: missing/non-string `module_dir`, unavailable `ModuleValidator`, and exceptions from `execute_full_validation`.
  - 1 new public function: `apply_and_validate_final_reconciliation_patch_plan(patch_plan, brief, module_dir=None) -> dict` orchestrator. Runs `apply_final_reconciliation_patch_plan` first; only invokes `run_final_reconciliation_schema_validation` when apply is `applied`. When apply is not `applied`, `schema_validation` is set to a small `{"status": "not_run", ...}` dict. Overall status is `applied` only when both phases pass; otherwise `failed`. The orchestrator does NOT attempt rollback; apply-side writes remain on disk when schema fails (rollback is a Step 4.3 concern). The apply_result is preserved verbatim so callers can read the underlying apply helper's `changed_files` and `diagnostics` directly.
- `scripts/test_toolkit_llm_final_reconciliation.py`
  - 7 new import names: 2 status constants, 2 diagnostic codes, 2 helper functions (`_parse_validator_error_message`, `collect_schema_validation_results`), 2 public functions (`run_final_reconciliation_schema_validation`, `apply_and_validate_final_reconciliation_patch_plan`).
  - 5 new test classes (33 new tests, all provider-free, see Section 7 below).
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 4.1 checked off with completion evidence)

## 3. Files Read (Context)

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/proposal.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/design.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Steps 1-3.5 evidence; Step 4.1 task spec)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-final-reconciliation-patch-contract/spec.md`
- `core/validation/validate_module_files.py` (read `ModuleValidator.__init__`, `results` defaultdict shape, `execute_full_validation`, `get_success_rate`, and several `validate_*` methods to understand the error string format; the helper does not assume a single error shape, so it parses the various forms conservatively)
- `utils/toolkit_llm_final_reconciliation.py` (Step 3.4 apply helper, Step 3.5 post-write validation, existing diagnostic infrastructure, status constants, error message builder)
- `scripts/test_toolkit_homebrew_readiness_gate.py` (reference pattern for `ModuleValidator(str(module_dir), str(REPO_ROOT))` instantiation; Step 4.1 mirrors this pattern)
- `scripts/test_toolkit_llm_final_reconciliation.py` (Step 3.4 apply-helper test scaffold `_TempModuleDirTestCase` and `_make_brief_with_module_dir` reused for Step 4.1 orchestrator tests)

## 4. Public Surface

### Newly exported constants (Step 4.1)

- `FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS = "pass"` - validator ran and reported no failed files.
- `FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL = "fail"` - validator ran and reported at least one failed file.
- `FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR = "error"` - validator could not be invoked or raised an exception.
- `FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_NOT_RUN = "not_run"` - validation was skipped because the apply phase did not produce changes (orchestrator-only).
- `DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED = "schema_validation_failed"` - emitted on the fail path so reports can key on the failure without walking the `errors` list.
- `DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR = "schema_validation_error"` - emitted on the error path (missing `module_dir`, unavailable `ModuleValidator`, or exception from `execute_full_validation`).

### Module-internal constant

- `_TOOLKIT_FINAL_RECONCILIATION_REPO_ROOT` (resolved from `Path(__file__).resolve().parents[1]`) - used to anchor the `ModuleValidator` schema dir. Not exported.

### Newly added pure helper functions

- `_parse_validator_error_message(raw_message) -> Tuple[Optional[str], str]` - best-effort `(file, message)` split for the various ModuleValidator error string shapes. Never mutates inputs; never raises; non-string inputs are coerced via `str(...)` and parsed. Whitespace is stripped; the FIRST colon is the separator so inner colons stay in the message portion.

- `collect_schema_validation_results(validator_results) -> Dict[str, Any]` - collapses a `ModuleValidator.results` mapping into the compact shape documented below. Pure: never mutates `validator_results`, never raises, handles non-dict inputs gracefully, skips legacy scalar category payloads, never includes the raw `files` lists.

### Newly added public functions

- `run_final_reconciliation_schema_validation(module_dir) -> dict` - instantiates `ModuleValidator(module_dir, repo_root)`, calls `execute_full_validation(verbose=False)`, routes through `collect_schema_validation_results`, and returns the structured shape. Fail-closed on three failure classes:
  1. `module_dir` is missing / not a string / empty string.
  2. `ModuleValidator` is unavailable (defensive import).
  3. `execute_full_validation` raises.

- `apply_and_validate_final_reconciliation_patch_plan(patch_plan, brief, module_dir=None) -> dict` - Step 4.1 orchestrator. Runs `apply_final_reconciliation_patch_plan` first; when the apply phase is `applied`, calls `run_final_reconciliation_schema_validation` next. The orchestrator does NOT attempt rollback; when apply succeeds but schema fails, the writes remain on disk (rollback is a Step 4.3 concern). The apply_result is preserved verbatim so callers can read the underlying apply helper's `changed_files` and `diagnostics` directly. When apply is anything other than `applied`, `schema_validation` is set to a small `{"status": "not_run", ...}` dict.

## 5. Return Shapes

### `collect_schema_validation_results(...)` success-path shape

```python
{
    "status": "pass" | "fail",
    "success_rate": float,  # 0.0 - 1.0
    "passed": int,           # total files/checks passed
    "failed": int,           # total files/checks failed
    "errors": [
        {
            "category": <results key>,
            "file": <best-effort file portion> | None,
            "message": <error message string>,
        },
        ...
    ],
}
```

The shape intentionally does NOT include the raw `files` lists so downstream reports stay small.

### `run_final_reconciliation_schema_validation(...)` shape

```python
{
    "status": "pass" | "fail" | "error",
    "success_rate": float,
    "passed": int,
    "failed": int,
    "errors": [...],          # compact per-error dicts
    "diagnostics": [...],     # structured diagnostics on fail/error paths
}
```

The `error` shape mirrors the success shape but carries `status: "error"`, a non-empty `diagnostics` list with one `schema_validation_error` entry, and the zeroed count fields.

### `apply_and_validate_final_reconciliation_patch_plan(...)` shape

```python
{
    "status": "applied" | "failed",
    "apply_result": {
        "status": "applied" | "failed",
        "changed_files": [...],
        "diagnostics": [...],
    },
    "schema_validation": {
        "status": "pass" | "fail" | "error" | "not_run",
        "success_rate": float,
        "passed": int,
        "failed": int,
        "errors": [...],
        "diagnostics": [...],
    },
    "diagnostics": [...],     # combined: apply diagnostics + schema diagnostics
}
```

## 6. Failure / Skip Semantics

### When apply fails (any non-`applied` status)

The orchestrator short-circuits BEFORE invoking `run_final_reconciliation_schema_validation`. The `schema_validation` field is set to `{"status": "not_run", "success_rate": 0.0, "passed": 0, "failed": 0, "errors": [], "diagnostics": []}`. The overall status is `failed`. The combined `diagnostics` list carries the apply-phase diagnostics. The apply-side writes (if any) remain on disk; rollback is a Step 4.3 concern.

### When apply succeeds and schema fails

The orchestrator does NOT attempt rollback. The apply_result is preserved as `applied` (so callers can read what was written), the `schema_validation` field carries the structured fail shape with a `schema_validation_failed` diagnostic, the combined `diagnostics` list carries both phases' diagnostics, and the overall status is `failed`.

### When apply succeeds and schema is `error`

Same as the fail branch; the `schema_validation` field carries the structured error shape with a `schema_validation_error` diagnostic.

## 7. Test Coverage

33 new tests added in 5 new test classes (all provider-free; all `ModuleValidator` instances are mocked at the import site via `unittest.mock.patch` so the real validation path is never invoked):

- `TestStep41Constants` (2 tests) - pins the four schema-validation status names and the two diagnostic codes.
- `TestParseValidatorErrorMessage` (7 tests) - simple `file: msg` split; area path with `(areas/)` suffix; no-separator input returns `(None, full_message)`; leading-colon input; non-string input via `str(...)`; whitespace stripping; inner-colon preservation.
- `TestCollectSchemaValidationResults` (10 tests) - pass path with all passed; fail path with two categories (one fully passed, one fully failed) verifying aggregation and per-error `category/file/message` shape; mixed pass/fail in same category; empty results returns pass with zero counts; non-dict input returns pass with zero counts; raw `files` field is excluded from compact shape (per-error dict also excludes `files`); unknown category payload is skipped safely; purity (no input mutation); compact shape keys pinned to the canonical five.
- `TestRunFinalReconciliationSchemaValidation` (6 tests) - happy pass path with mocked `ModuleValidator` (asserts `MockValidator` was called with the given `module_dir` and a non-empty string schema dir, and that `execute_full_validation(verbose=False)` was invoked exactly once); fail path with mocked validator that returns a single failure; exception path with mocked validator that raises from `execute_full_validation`; missing/empty `module_dir` returns structured error without instantiating validator; non-string `module_dir` (None, int, list, dict) returns structured error; `ModuleValidator = None` (defensive import path) returns structured error.
- `TestApplyAndValidateFinalReconciliationPatchPlan` (8 tests, all extending `_TempModuleDirTestCase`) - overall `applied` when both phases pass; overall `failed` when apply succeeds but schema fails (writes remain on disk, no rollback); schema validation is NOT invoked when apply fails (target-read-failed path); schema validation is NOT invoked when plan-level validation fails (refused status path); schema `error` propagates as overall `failed`; explicit `module_dir` argument takes precedence over brief's `module_dir` for schema validation; no mutation of inputs; combined `diagnostics` list correctly merges both phases; top-level orchestrator result shape keys are pinned to `{status, apply_result, schema_validation, diagnostics}`.

## 8. Verification

- `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
- `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **373 PASS, 0 FAIL** in 0.054s (was 340; +33 new tests)
- `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **106/106 OK** in 0.097s (no regression in dependent suites)
- `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
- `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID

## 9. Scope Confirmation

- No live provider call in tests: confirmed (all 33 new tests are provider-free; `run_final_reconciliation_schema_validation` always uses a mocked `ModuleValidator`).
- No packet-builder integration: confirmed (no edits to `web/extensions/toolkit_homebrew_packet_builder.py` or any other packet-builder file in this step).
- No readiness/publishability/report-agreement gates: confirmed (Step 4.1 only invokes `ModuleValidator`; readiness, publishability, and report agreement are owned by Step 4.2).
- No report persistence: confirmed (no call to `persist_final_reconciliation_report(...)`; Step 4.4 is reserved).
- No retry loop: confirmed (single schema-validation call per orchestrator invocation; retry is a Step 4.3 concern).
- No rollback attempt: confirmed (the orchestrator explicitly documents that when apply succeeds but schema fails, the writes remain on disk; rollback is a Step 4.3 concern).
- No live filesystem leak in tests: confirmed (every new orchestrator test extends `_TempModuleDirTestCase`; pure helper tests use no filesystem at all).
- ASCII-only: confirmed (0 violations across both files).
- No mutation of inputs: confirmed (the orchestrator's `apply_result` is preserved verbatim; the new `_parse_validator_error_message` and `collect_schema_validation_results` helpers are read-only by construction; the orchestrator's purity is explicitly tested in `TestApplyAndValidateFinalReconciliationPatchPlan.test_does_not_mutate_inputs`).
- Compact shape: confirmed (the compact shape does NOT include the raw `files` lists; per-error dict also excludes `files`; this is explicitly tested in `TestCollectSchemaValidationResults.test_does_not_include_files_field`).
- ModuleValidator invocation: confirmed (`MockValidator.assert_called_once()` in the pass-path test verifies that `ModuleValidator(module_dir, schema_dir)` is invoked with the given `module_dir` and a non-empty string schema dir).
- Schema validation skip semantics: confirmed (the orchestrator's "not_run" branch is tested in two ways: target-read-failed apply path and refused plan path; both tests assert `mock_schema.assert_not_called()`).
