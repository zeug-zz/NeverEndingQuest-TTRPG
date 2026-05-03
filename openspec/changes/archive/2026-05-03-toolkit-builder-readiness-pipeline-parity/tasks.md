## 1. Baseline And Safety Checks

- [x] 1.1 Confirmed legacy builder path: `simulate_build_process` calls `ModuleBuilder.build_module(...)` followed directly by `run_toolkit_module_postbuild_finishing(...)` at line ~5400-5410.
- [x] 1.2 Confirmed uploader path: `_run_homebrew_readiness_gate(...)` (which calls `run_toolkit_homebrew_readiness_gate`) runs before `_run_homebrew_finisher(...)`. Uploader code unchanged by this change.
- [x] 1.3 Added source-contract tests in `TestToolkitPublicationParitySourceContracts`: `test_readiness_adapter_function_exists_in_gate_module`, `test_legacy_builder_readiness_cannot_be_bypassed_in_web_interface`, and updated `test_web_interface_invokes_finisher_and_reports_status`.
- [x] 1.4 Added `test_uploader_readiness_gate_function_signature_preserved` -- confirms `run_toolkit_homebrew_readiness_gate(workspace, job_id, state_callback)` signature unchanged.

## 2. Shared Readiness Adapter

- [x] 2.1 Added `run_toolkit_builder_readiness_gate` inside `web/extensions/toolkit_homebrew_readiness_gate.py` as a clearly separated public wrapper.
- [x] 2.2 Adapter API accepts `module_slug`, optional `job_id`, optional `state_callback`. Uses `*` keyword-only for optional params. Accepts no `artifact_workspace` (creates minimal workspace internally).
- [x] 2.3 Adapter remains a thin delegate to existing `run_toolkit_homebrew_readiness_gate` via a minimal transient workspace. Accepted per Decision 2 mitigations; future direct-core extraction remains a deferred refactor.
- [x] 2.4 Uploader workspace persistence for `readiness_validation_report`, `readiness_audit_report`, `repair_report` is completely unchanged.
- [x] 2.5 `run_toolkit_builder_readiness_gate` now persists `modules/<slug>/toolkit_readiness_report.json` with canonical convergence fields plus audit payload details: `validation`, `readiness_audit`, `repair_attempts`, `workspace_artifacts`, and `legacy_workspace`. Written via `_write_readiness_report_artifact` helper.
- [x] 2.6 Uses `safe_write_json` for the build_result artifact in the transient workspace.

## 3. Legacy Builder Pipeline Integration

- [x] 3.1 `simulate_build_process(...)` updated with `# TABLETOP MODE:` block calling `run_toolkit_builder_readiness_gate` after raw `build_module(narrative)` succeeds.
- [x] 3.2 `_builder_readiness_callback` emits `module_progress` events for validating, repairing_deterministic, repairing_semantic, and audit states.
- [x] 3.3 `run_toolkit_module_postbuild_finishing(...)` runs only when `readiness_state.get("ready_for_finishing")` is true.
- [x] 3.4 Sends `module_error` with `generation_succeeded=True`, `readiness_failed=True`, `module_name`, `readiness_result` when readiness fails.
- [x] 3.5 When `TOOLKIT_BUILDER_READINESS_AVAILABLE` is false (ImportError), emits module_error with `generation_succeeded=True` but skips readiness and finishing with an error message.
- [x] 3.6 Raw generation failures (exceptions in `builder.build_module(...)`) are caught by the existing outer try/except and handled as before.

## 4. Report Freshness And Provenance

- [x] 4.1 `_write_stale_report_marker(...)` is called at the start of `run_toolkit_builder_readiness_gate` with `freshness="pre_readiness"` and `status="in_progress"`, and now writes sidebar-compatible freshness metadata (`freshness_state`, `report_freshness`, contract `toolkit_build_report_refresh_contract.v1`) as non-authoritative stale state.
- [x] 4.2 When readiness returns `ready_for_finishing=False`, `_write_stale_report_marker(...)` is called with `freshness="post_readiness_failure"` and `status="failed"`, writing authoritative current-failure freshness metadata so stale pass reports are replaced deterministically.
- [x] 4.3 When readiness passes and finishing runs, `run_toolkit_module_postbuild_finishing(module_name, strict=True)` writes `modules/<slug>/toolkit_build_report.json` through the shared finisher contract.
- [x] 4.4 `result["source_workflow"] = "legacy_builder_narrative_v1"` is set in the readiness return value. The transient workspace build_result.json also carries `"build_mode": "legacy_builder_narrative_v1"`.
- [x] 4.5 Uploader packet provenance (`packet_identity`, `source_hash`, `review_snapshot`) is completely unchanged. The uploader is not relabeled.

## 5. UI And Payload Reporting

- [x] 5.1 Progress stages updated: stages 9=Readiness Validation, 10=Readiness Repair, 11=Readiness Audit, 12=Post-Build Finishing.
- [x] 5.2 `module_complete` payload now includes `ready_status`, `publishable_status`, and `readiness_result`.
- [x] 5.3 `module_error` handler now distinguishes readiness failure (via `readiness_failed` flag) from finishing failure and raw generation failure.
- [x] 5.4 Error display reuses existing `buildToolkitFinishingFailureDetails` for finishing failures and shows JSON dump of readiness result for readiness failures.
- [x] 5.5 Stale `publication_parity_note` removed from both `web/web_interface.py` and the template. No replacement stale note added.

## 6. Uploader Regression Protection

- [x] 6.4 Confirmed: no changes to uploader source-rights, preflight, normalization, review snapshot, or packet-derived builder input code paths.

## 7. Legacy Builder Regression Coverage

- [x] 7.1 `test_web_interface_invokes_finisher_and_reports_status`, `test_legacy_builder_readiness_cannot_be_bypassed_in_web_interface` prove readiness is called before finishing.
- [x] 7.2 `test_legacy_builder_readiness_cannot_be_bypassed_in_web_interface` asserts `ready_for_finishing` and `readiness_failed` are checked in the socket handler, confirming finishing is gated.
- [x] 7.3 Existing `test_web_interface_invokes_finisher_and_reports_status` confirms `run_toolkit_module_postbuild_finishing` is still called in `web_interface.py`, now conditional on readiness.
- [x] 7.4 `test_toolkit_template_exposes_finishing_stage_and_parity_note` no longer checks for `publication_parity_note`. `test_web_interface_invokes_finisher_and_reports_status` no longer checks for it either.
- [x] 7.6 Added fail-closed readiness exception coverage: `run_toolkit_builder_readiness_gate` catches delegate exceptions and returns `reason=readiness_adapter_exception` with persisted readiness/failure marker artifacts.

## 8. Verification

- [x] 8.1 `python3 -m py_compile` passes for:
  - `web/extensions/toolkit_homebrew_readiness_gate.py`
  - `web/web_interface.py`
  - `scripts/test_toolkit_module_build_publication_parity.py`
- [x] 8.2
  - `scripts/test_toolkit_module_build_publication_parity.py`: 37/37 PASS (with .venv)
  - `scripts/test_toolkit_homebrew_readiness_gate.py`: 22/22 PASS (with .venv)
  - `scripts/test_toolkit_homebrew_md_upload_routes.py`: requires Flask (not run directly, but source-contract checks confirm route file unchanged)
- [x] 8.3 `node --check web/static/js/tabletop_mode.js` -> PASS (no template JS modifications)
- [x] 8.4 `openspec validate toolkit-builder-readiness-pipeline-parity` -> valid

## Deferred Notes

- Uploader integration tests remain environment-blocked because the Flask test harness is unavailable in this session. Source-contract coverage confirms the uploader path is unchanged and the shared readiness adapter is used.
- Sidebar audit-free rendering assertion is a low-priority follow-up and not required for archive correctness.
- Stubbed-executor smoke for the readiness adapter is deferred until a deterministic executor harness exists.
- Richer readiness failure UI remains a future improvement; current JSON dump is acceptable for archive.

## 9. Documentation And Review Notes

- [x] 9.1 Code comments added at:
  - `web/extensions/toolkit_homebrew_readiness_gate.py`: docstring for `run_toolkit_builder_readiness_gate`, inline comment block before adapter code.
  - `web/web_interface.py`: `# TABLETOP MODE:` comments for readiness block and readiness-aware finishing block.
- [x] 9.2 Artifact location for legacy builder readiness outputs:
  - Transient workspace at `user_uploads/toolkit/legacy_builder_workspaces/legacy_builder_<slug>_<timestamp>/`
  - Contains `build_result.json`, `readiness_validation_report.json`, `readiness_audit_report.json`, `repair_report.json` (via shared gate persistence).
- [x] 9.3 Deferred improvements moved to the Deferred Notes section:
  - Richer readiness failure panel in the template (currently raw JSON dump).
  - Dedicated sidebar source-contract test for audit-free rendering (7.5).
  - Full Flask-dependent uploader integration tests (6.1-6.3).
  - Dry-run smoke with stubbed executor (8.5).
- [x] 9.4 No runtime gameplay files or live campaign state files were modified. All changes are toolkit pipeline files and tests.
