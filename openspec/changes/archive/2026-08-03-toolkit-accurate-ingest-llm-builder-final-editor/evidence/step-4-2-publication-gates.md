# Step 4.2 Evidence: Post-Accepted-Reconciliation Publication Gates

## Summary

Implemented Step 4.2 of the OpenSpec change
`toolkit-accurate-ingest-llm-builder-final-editor`. Added the
`run_final_reconciliation_publication_gates(...)` helper that runs
readiness, publishability, and report agreement after accepted
reconciliation, plus the
`apply_validate_and_gate_final_reconciliation_patch_plan(...)`
orchestrator that composes the Step 4.1 apply+validate path with the
new gate phase. Source-fidelity honesty is preserved: the helper pins
`source_fidelity_effective_status="reconciled_degraded"` and
`final_reconciliation_accepted=True` on every gate result, and
normalizes the `effective_publishable_status` passed to the report
agreement composer only when the raw effective status is blocked
solely because of source fidelity and `publishable_status` is pass.

## Public helpers added

- `utils.toolkit_llm_final_reconciliation.run_final_reconciliation_publication_gates(module_dir, schema_validation=None, source="toolkit") -> dict`
  - Resolves module slug from `module_dir.name`.
  - Calls `audit_module_readiness`, `audit_module_publishability`, and
    `compose_report_agreement` in that order.
  - Catches every helper exception fail-closed with a structured
    `gate_helper_exception` diagnostic.
  - Returns a compact 14-key result shape:
    `status`, `readiness`, `publishability`, `report_agreement`,
    `diagnostics`, `ready_status`, `publishable_status`,
    `effective_publishable_status`,
    `effective_publishable_status_raw`,
    `effective_publishable_status_normalized`, `validation_status`,
    `source_fidelity_effective_status`,
    `final_reconciliation_accepted`,
    `final_reconciliation_status`.
- `utils.toolkit_llm_final_reconciliation.apply_validate_and_gate_final_reconciliation_patch_plan(patch_plan, brief, module_dir=None) -> dict`
  - Calls the Step 4.1 orchestrator first.
  - If the Step 4.1 result is not `applied`, returns `failed` with
    `gates.status="not_run"` and skips the gate helpers entirely.
  - If applied, runs the gate runner with the same `module_dir` and
    the Step 4.1 schema-validation payload.
  - Returns a stable 5-key result:
    `status`, `apply_result`, `schema_validation`, `gates`,
    `diagnostics`.
  - Overall status is `applied` only when the gate phase also
    returns `pass`.

## Stable constants added

- `FINAL_RECONCILIATION_GATE_STATUS_PASS = "pass"`
- `FINAL_RECONCILIATION_GATE_STATUS_FAIL = "fail"`
- `FINAL_RECONCILIATION_GATE_STATUS_ERROR = "error"`
- `FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN = "not_run"`
- `FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS = "reconciled_degraded"`
- `FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS = "accepted"`

## Diagnostic codes added

- `DIAGNOSTIC_CODE_GATE_READINESS_FAILED = "gate_readiness_failed"`
- `DIAGNOSTIC_CODE_GATE_PUBLISHABILITY_FAILED = "gate_publishability_failed"`
- `DIAGNOSTIC_CODE_GATE_REPORT_AGREEMENT_BLOCKED = "gate_report_agreement_blocked"`
- `DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION = "gate_helper_exception"`

## Private helpers added

- `_normalize_schema_validation_to_validation_status(schema_validation) -> str`
  - Maps `pass -> pass`, `fail/error -> blocked`,
    `not_run -> unknown`, missing/None/non-dict/non-string/garbage
    -> `unknown`.
- `_compute_reconciled_publishable_status(publishability_report) -> (str, bool)`
  - Returns `(publishable_status, True)` ONLY when:
    1. raw `effective_publishable_status` is blocked/fail, AND
    2. `publishable_status` is pass, AND
    3. `source_fidelity_status` is blocked/degraded/fail.
  - Otherwise returns `(raw_effective_status, False)`.
  - The check intentionally does NOT normalize when
    `publishable_status` itself is fail so a real publishability
    failure cannot be hidden.

## Defensive imports

The three gate helpers are imported defensively:

- `from scripts.audit_module_readiness import audit_module_readiness`
- `from scripts.audit_module_publishability import audit_module_publishability`
- `from utils.toolkit_report_agreement import compose_report_agreement`

Each is wrapped in `try/except` so the module remains importable in
environments where the script or utility packages are unavailable. In
that case the import sentinel is `None` and the gate helper returns
`error` with a `gate_helper_exception` diagnostic. Tests always
patch these targets via `unittest.mock.patch` so the real
implementations are never called.

## Tests added

- `TestStep42Constants` (10 tests) - pins the four gate status
  names, two reconciliation gate facts, and four diagnostic codes.
- `TestNormalizeSchemaValidationToValidationStatus` (9 tests) -
  pass/fail/error/not_run mapping, missing/None/non-dict/non-string/
  garbage input handling.
- `TestComputeReconciledPublishableStatus` (7 tests) - all-pass no
  normalization, blocked/degraded fidelity-only normalization,
  publishable_fail does NOT normalize, pass_fidelity_blocked_effective
  no normalize, missing/empty-report handling.
- `TestRunFinalReconciliationPublicationGates` (20 tests) - happy
  path pass, readiness fail, publishability fail, report agreement
  blocked, three helper-exception paths (readiness, publishability,
  agreement), source-fidelity reconciled normalization, Path
  module_dir accepted, str module_dir accepted, invalid/empty
  module_dir returns error, no schema_validation defaults to
  unknown, schema_validation_fail/error normalizes to blocked, three
  non-dict-response defensive tests, gate result shape stability.
- `TestApplyValidateAndGateFinalReconciliationPatchPlan` (8 tests) -
  all-three-phases pass, applies-skips-gates on apply fail,
  applies-skips-gates on schema fail, gates fail -> overall failed
  (and apply wrote to disk), gate helpers invoked exactly once on
  success, no-mutation input contract, top-level shape keys pinned,
  not_run gates payload carries accepted-reconciliation fields,
  schema validation payload is forwarded into the gate payload.

All 54 new tests mock the readiness, publishability, agreement, and
schema-validation helpers via `unittest.mock.patch` so no live CLI
subprocess runs and no live report is loaded.

## Test counts

- 373 (Step 4.1 baseline) -> **427** (Step 4.1 + 54 Step 4.2).
- All 427 pass with no live provider call and no live CLI subprocess.

## Verification

- `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
- `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **427 PASS, 0 FAIL** in 0.069s
- `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts/test_file_operations_path_safety` -> **106/106 OK** in 0.094s
- `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
- `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
- `openspec validate --specs` -> 364/364 PASS

## Scope confirmation

- No live provider call in tests (all gate helpers mocked).
- No packet-builder integration (Step 5 is still pending).
- No report persistence (Step 4.4 is still pending).
- No retry loop (Step 4.3 is still pending).
- No mutation of `module_dir`/`patch_plan`/`brief` inputs.
- No production code paths added beyond the new helper and
  orchestrator; existing Step 1-4.1 helpers are unchanged.
