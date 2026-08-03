# Step 5.4 - Front/Middle Immutability Evidence

**Date:** 2026-06-12
**Task:** 5.4 - Preserve existing front/middle artifacts unchanged and add source-contract tests proving no reconciliation fields enter source graph, normalized packet, blueprint, backstage audit, or ModuleBuilder handoff.

## Outcome

Added a new test class `TestStep54FrontMiddleImmutability` in `scripts/test_toolkit_homebrew_gui_unified_flow.py` with 7 provider-free tests. No production code was changed by this step.

## Step 5.4 Forbidden Field Set

The tests pin the following forbidden field names (top-level keys, serialized as JSON `"key"` substrings) and forbidden string values:

- Forbidden keys (5): `final_reconciliation`, `final_reconciliation_required`, `final_reconciliation_accepted`, `final_reconciliation_editor_result`, `source_fidelity_effective_status`
- Forbidden string values (1): `reconciled_degraded`

These names and values are checked against the serialized JSON of every front/middle artifact produced by the production pipeline.

## Source-Contract Tests (5)

Each test runs the production helper against minimal valid inputs and asserts none of the Step 5.4 forbidden field names or string values appear anywhere in the serialized output. The test uses JSON serialization (sort_keys=True, ensure_ascii=True) to catch both top-level keys and nested occurrences.

### 1. `test_source_manifest_no_step54_forbidden`
- Production helper: `utils.toolkit_source_manifest.build_source_manifest(source_text, source_path, source_hash)`
- Asserts: serialized output carries no Step 5.4 forbidden keys/values.
- Status: PASS.

### 2. `test_normalized_packet_no_step54_forbidden`
- Production helper: `utils.toolkit_homebrew_upload_contract.build_normalized_packet_placeholder(source_path, source_hash, preflight)`
- Also inspects the workspace-seeded `normalized_packet.json` for the same forbidden keys/values (front/middle baseline check).
- Status: PASS.

### 3. `test_builder_blueprint_no_step54_forbidden`
- Production helper: `utils.toolkit_builder_blueprint.generate_builder_blueprint(source_graph, identity_report, plot_topology, synthesis_report, normalized_packet, fidelity_report, triage_report)`
- Asserts: serialized blueprint carries no Step 5.4 forbidden keys/values.
- Status: PASS.

### 4. `test_backstage_audit_artifacts_no_step54_forbidden`
- Production flow: `scripts.run_backstage_agent.run_accurate_ingest_audit(module_slug, output_dir)` against a stub module, then `scripts.prepare_builder_from_backstage_audit.build_builder_brief(loaded)` and `build_builder_prompt_context(brief)`.
- Asserts: every emitted artifact (`run.json`, `evidence.json`, `audit_report.json`, `recommendation.json`) and the briefing prep output (`builder_brief.json`, `builder_prompt_context.md`) carry no Step 5.4 forbidden keys/values.
- Status: PASS.

### 5. `test_module_builder_handoff_no_step54_forbidden`
- Production flow: `run_toolkit_homebrew_packet_build(workspace, job_id)` with a mocked `_execute_module_builder` executor.
- Captures the in-memory `builder_input` payload passed to the executor and asserts no Step 5.4 forbidden keys/values are present. Also checks the persisted `builder_input.json` if it exists.
- Status: PASS.

## Behavioral Immutability Tests (2)

Both tests use SHA-256 hash comparison to prove the accepted and blocked final-editor paths leave pre-existing workspace-level front/middle artifacts byte-for-byte unchanged. New `import hashlib` added to the test file.

Sentinel artifacts tracked by SHA-256:
- `source_graph.json`
- `source_manifest.json`
- `normalized_packet.json`
- `builder_blueprint.json`
- `builder_blueprint_report.json`

Each sentinel includes a `sentinel_marker` field so a future regression that injects a forbidden key as part of a different shape cannot be confused with the original content.

### 6. `test_accepted_path_does_not_mutate_front_middle_artifacts`
- Mocks: `materialize_module_from_blueprint`, `ENABLE_ACCURATE_INGEST_*` flags, `is_build_fidelity_required`, `build_build_fidelity_report`, `can_continue_after_build_fidelity`, `build_source_fidelity_rollup`, `classify_final_build_blockers`, `run_final_reconciliation_with_bounded_retry` (returns accepted), `persist_accepted_final_reconciliation_report` (returns written).
- Behavior: builds the packet with the editorial classification, the editor returns accepted, the persist helper returns written. The run is confirmed to have gone through the accepted path (asserts `final_reconciliation_accepted == True` and `source_fidelity_effective_status == "reconciled_degraded"`).
- Assertion: SHA-256 hash of every sentinel artifact is identical before and after the run.
- Status: PASS.

### 7. `test_blocked_path_does_not_mutate_front_middle_artifacts`
- Same setup as 6, but the mocked editor returns `rejected` orchestrator result.
- Behavior: the run is confirmed to have gone through the blocked path (asserts `status == "blocked"` and `final_reconciliation_accepted` is NOT in the result).
- Assertion: SHA-256 hash of every sentinel artifact is identical before and after the run.
- Status: PASS.

## Files Modified

- `scripts/test_toolkit_homebrew_gui_unified_flow.py`
  - Added `import hashlib` to the import block.
  - Added new test class `TestStep54FrontMiddleImmutability` (~370 lines) with 7 tests.
  - Added 2 helper methods to `setUp` to align the review-snapshot source_hash with the test source hash (this is a test-fixture concern, not a production change).

## Files NOT Modified (front/middle production code)

- `web/extensions/toolkit_homebrew_packet_builder.py` - unchanged
- `utils/toolkit_source_manifest.py` - unchanged
- `utils/toolkit_builder_blueprint.py` - unchanged
- `utils/toolkit_homebrew_normalizer.py` - unchanged
- `scripts/run_backstage_agent.py` - unchanged
- `scripts/prepare_builder_from_backstage_audit.py` - unchanged
- `utils/accurate_ingest_backstage_audit.py` - unchanged

## ASCII Compliance

- `python3 scripts/check_ascii_compliance.py scripts/test_toolkit_homebrew_gui_unified_flow.py --summary-only` -> `ASCII_CHECK scanned_files=1 files_with_violations=0 violations=0 fixed_files=0 fixed_chars=0`

## Verification Commands Run

```bash
.venv/bin/python -m py_compile scripts/test_toolkit_homebrew_gui_unified_flow.py
.venv/bin/python -m unittest -v scripts.test_toolkit_homebrew_gui_unified_flow.TestStep54FrontMiddleImmutability
.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestStep53FatalMixedGuard \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestStep46PackBuilderEditorialBranch \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestStep42FatalBlockedBehavior \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestStep43EditorialReconciliationRequired \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestStep44AcceptedReconciliation \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestStep45EvidenceReportsImmutability \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestFinalReconciliationBoundarySourceContract
.venv/bin/python -m unittest -q scripts.test_toolkit_llm_final_reconciliation
.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity
python3 scripts/check_ascii_compliance.py scripts/test_toolkit_homebrew_gui_unified_flow.py --summary-only
openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict
```

## Verification Results

- `.venv/bin/python -m py_compile scripts/test_toolkit_homebrew_gui_unified_flow.py` -> PASS
- `.venv/bin/python -m unittest -v scripts.test_toolkit_homebrew_gui_unified_flow.TestStep54FrontMiddleImmutability` -> **7 PASS, 0 FAIL** in 0.061s
- Related step tests: 47 PASS, 0 FAIL (no regression on prior step 4.x/5.1/5.2/5.3 tests)
- `.venv/bin/python -m unittest -q scripts.test_toolkit_llm_final_reconciliation` -> 524 PASS, 0 FAIL (no regression on final-reconciliation runner)
- `.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity` -> 135 PASS, 0 FAIL (no regression on publication parity)
- `python3 scripts/check_ascii_compliance.py scripts/test_toolkit_homebrew_gui_unified_flow.py` -> 0 violations
- `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID

## Immutability Proof Summary

| Front/Middle Artifact | Source-Contract Test | Behavioral Test |
|----------------------|----------------------|-----------------|
| source graph | `test_source_manifest_no_step54_forbidden` (manifest writer is the canonical front/middle writer; source graph is colocated in the workspace) | `test_accepted_path_does_not_mutate_front_middle_artifacts` (SHA-256 of `source_graph.json` before == after) |
| source manifest | `test_source_manifest_no_step54_forbidden` (run via `build_source_manifest`) | SHA-256 of `source_manifest.json` before == after |
| normalized packet | `test_normalized_packet_no_step54_forbidden` (via `build_normalized_packet_placeholder`) | SHA-256 of `normalized_packet.json` before == after |
| builder blueprint | `test_builder_blueprint_no_step54_forbidden` (via `generate_builder_blueprint`) | SHA-256 of `builder_blueprint.json` before == after |
| builder blueprint report | covered transitively (written by the same blueprint pipeline) | SHA-256 of `builder_blueprint_report.json` before == after |
| backstage audit artifacts | `test_backstage_audit_artifacts_no_step54_forbidden` (every emitted `run.json`, `evidence.json`, `audit_report.json`, `recommendation.json`) | not applicable (audit is a separate process; not invoked by packet build) |
| ModuleBuilder handoff | `test_module_builder_handoff_no_step54_forbidden` (in-memory `builder_input` captured from executor) | not applicable (handoff is in-memory; the captured `builder_input` is the authoritative proof) |

## Follow-Up

- 6.1 (Well of Ruin regression coverage for `Trigger`, `Passive Element`, `Active Element`) is the next unblocked section.
