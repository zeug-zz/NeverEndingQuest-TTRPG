# Step 5.1: Packet Builder Final Editor Invocation

**Status:** COMPLETED 2026-06-12

## Objective

Invoke the LLM Builder final editorial reconciliation pass from
`web/extensions/toolkit_homebrew_packet_builder.py` whenever the editorial
classification requires reconciliation and no fatal blockers are present.
Replace the legacy "pause at `final_reconciliation_required` and wait for a
human to act" flow with a live invocation of the Step 4.3 orchestrator.

## Files Changed

### Production Code

- `web/extensions/toolkit_homebrew_packet_builder.py`
  - New module-internal helper `_invoke_final_editor_or_fallback(...)` that
    owns the Step 5.1 live-invocation contract.
  - Replaced the legacy 4.3 `final_reconciliation_required` pause inside the
    editorial branch with a call to the new helper.
  - Defensive import block for
    `utils.toolkit_llm_final_reconciliation.run_final_reconciliation_with_bounded_retry`,
    `persist_accepted_final_reconciliation_report`, and
    `build_blocked_final_reconciliation_report`.
  - Failed-import branch restores the legacy
    `final_reconciliation_required` pause (per task 5.1 step 6) so the
    build is not silently lost.
  - Live editor invocation uses `module_dir=str(module_dir)` derived from
    `Path(params["output_directory"]).resolve()` (same as the rest of the
    fidelity layer).
  - Persist-failure path constructs a minimal `blocked` metadata shape
    directly (does NOT delegate to `build_blocked_final_reconciliation_report`
    because that helper passes through to the accepted report for accepted
    orchestrator results).
  - Non-accepted orchestrator status (`rejected`, `not_retryable`,
    `invalid_brief`, etc.) shapes metadata via
    `build_blocked_final_reconciliation_report` and sets
    `status: blocked, stage: final_reconciliation,
     error: final_reconciliation_editor_rejected:<status>`.
  - Editor-exception path sets
    `error: final_reconciliation_editor_exception:<error>` and never
    claims accepted or clean pass.
  - Source-fidelity honesty invariant: accepted metadata always emits
    `source_fidelity_effective_status: reconciled_degraded` (never `pass`,
    `clean_pass`, `clean`, or `source_fidelity_pass`).

### Tests

- `scripts/test_toolkit_homebrew_gui_unified_flow.py`
  - Replaced the 4.3 test `test_no_accepted_report_returns_reconciliation_required`
    with `test_no_accepted_report_editor_rejected_remains_blocked`. The new
    test mocks the editor to return non-accepted, asserts the new blocked
    state, and confirms the brief is still persisted before the editor
    invocation.
  - Added new test class `TestStep51FinalEditorInvocation` (9 tests, all
    provider-free via `unittest.mock.patch` on the helper API source
    module):
    - `test_packet_builder_source_imports_final_editor` (source contract)
    - `test_packet_builder_uses_helper_function` (source contract)
    - `test_editorial_editor_accepted_persists_and_continues` (accepted
      path: `final_reconciliation_accepted=True`,
      `source_fidelity_effective_status=reconciled_degraded`, report file
      on disk, `build_result.json` reflects accepted metadata)
    - `test_editorial_editor_persist_failure_remains_blocked` (persist
      fails: blocked, blocked metadata shape, report file NOT created)
    - `test_editorial_fatal_classification_does_not_invoke_editor` (Step
      5.3 source contract: `run_final_reconciliation_with_bounded_retry`
      is not called for fatal classification)
    - `test_editorial_unknown_classification_does_not_invoke_editor`
      (Step 5.3 source contract: same for unknown)
    - `test_editorial_accepted_status_never_claims_clean_pass` (honest
      source-fidelity contract: never `pass` / `clean_pass` / `clean` /
      `source_fidelity_pass`)
    - `test_editorial_editor_exception_remains_blocked` (live-provider
      exception: blocked, persist helper NOT called)
    - `test_editorial_helper_api_import_fails_falls_back` (Step 5.1 step
      6: import failure restores legacy
      `final_reconciliation_required` pause)

## Verification

- `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py scripts/test_toolkit_homebrew_gui_unified_flow.py` -> PASS
- `.venv/bin/python -m unittest -v scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation` -> 9 PASS, 0 FAIL
- `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep43EditorialReconciliationRequired scripts.test_toolkit_homebrew_gui_unified_flow.TestStep44AcceptedReconciliation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep45EvidenceReportsImmutability scripts.test_toolkit_homebrew_gui_unified_flow.TestStep46PackBuilderEditorialBranch scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep42FatalBlockedBehavior` -> 35 PASS, 0 FAIL
- `.venv/bin/python -m unittest -q scripts.test_toolkit_llm_final_reconciliation` -> 524 PASS, 0 FAIL
- `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID

## Contract Pinning

- Editorial + no accepted report + brief persist OK + editor accepted ->
  accepted metadata, `reconciled_degraded`, continue to normal
  build-result persistence.
- Editorial + no accepted report + brief persist OK + editor non-accepted
  -> `status: blocked, stage: final_reconciliation,
     error: final_reconciliation_editor_rejected:<status>`.
- Editorial + no accepted report + brief persist OK + editor accepted +
  persist fails -> `status: blocked, stage: final_reconciliation,
     error: final_reconciliation_persist_failed:...`.
- Editorial + helper API import fails -> legacy
  `final_reconciliation_required` pause (Step 5.1 step 6 fallback).
- Fatal / mixed / unknown classification -> existing
  `status: blocked, stage: build_fidelity,
   error: build_fidelity_blocked:...` path; editor never invoked.

## Out of Scope (Step 5.2+)

- The accepted reconciliation now flows through normal build-result
  persistence. Step 5.2 is responsible for wiring the post-build finisher
  and report agreement to consume the accepted metadata.
- The blocked reconciliation paths (rejected, persist-fail, exception)
  surface `final_reconciliation_editor_result` for diagnostic
  downstream consumption, but the report agreement composer integration
  is owned by Step 5.2.
- The `source_enhanced_*` packet fields and front/middle pipeline
  artifacts (source graph, normalized packet, blueprint, backstage
  audit) are unchanged; the new code reads and writes only the
  final-editor artifacts (`final_reconciliation_brief.json`,
  `final_reconciliation_report.json`, `build_result.json`,
  `build_fidelity_report.json`, `source_fidelity_report.json`).
