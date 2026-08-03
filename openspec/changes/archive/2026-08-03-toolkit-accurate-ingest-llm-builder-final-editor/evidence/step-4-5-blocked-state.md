# Step 4.5 Evidence - Blocked Final Reconciliation State

## Summary

Implemented a blocked final reconciliation report shape for failed or blocked
LLM Builder final-editor outcomes. Non-accepted outcomes now have explicit
diagnostics and cannot claim playable publication.

## Production Changes

- `utils/toolkit_llm_final_reconciliation.py`
  - Added `FINAL_RECONCILIATION_REPORT_STATUS_BLOCKED = "blocked"`.
  - Added `build_blocked_final_reconciliation_report(orchestrator_result, brief)`.
  - Non-accepted outcomes return:
    - `status: blocked`
    - `reconciliation_status: blocked`
    - `source_fidelity_effective_status: blocked`
    - `playable_publication_candidate: False`
    - empty `decisions`
    - empty `changed_files`
    - compact diagnostics from orchestrator result and attempts
  - Accepted outcomes delegate to the accepted report builder and preserve
    `source_fidelity_effective_status: reconciled_degraded`.
  - No file writes or report persistence happen in the blocked helper.

## Tests

- `scripts/test_toolkit_llm_final_reconciliation.py`
  - Added `TestStep45BlockedFinalReconciliationReport` with 5 tests.
  - Covered blocked non-playable status, compact diagnostics, legacy acceptance
    rejection, accepted delegation, and no persistence for non-accepted results.

## Verification

- `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
- `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> 524 PASS, 0 FAIL
- `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> 0 violations
- `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID

## Scope

- No live provider calls.
- No packet-builder or finisher integration.
- No retry behavior changes.
- No accepted report persistence for blocked outcomes.
- Non-accepted outcomes do not claim playable publication.
