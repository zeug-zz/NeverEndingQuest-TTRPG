# Step 6.3 Evidence: Final-editor negative tests

**Date:** 2026-06-12
**Step:** 6.3
**OpenSpec change:** `toolkit-accurate-ingest-llm-builder-final-editor`
**Specs covered:**
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-final-json-validation-loop/spec.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-final-reconciliation-patch-contract/spec.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-llm-builder-final-editorial-pass/spec.md`

## What was proved

Task 6.3 added a focused negative-test pass that locks the final
editor's fail-closed contract across the five spec-mandated negative
classes (invalid LLM JSON, forbidden file edits, runtime-only target
edits, false clean source-fidelity claims, provider unavailable) and
the packet-builder fatal/mixed guard. All tests are provider-free
(`mock_provider_output=...` short-circuit, `unittest.mock.patch` on
`create_chat_client`, `compose_report_agreement`, and the three gate
helpers; per-test tempdir; no live LLM, no live CLI subprocess, no
real `modules/` tree touched).

### 1. Invalid LLM JSON (5 tests, `TestStep63InvalidJsonNegative`)

End-to-end through `run_llm_final_editor(mock_provider_output=...)`:

- Raw English prose, empty string, JSON array, malformed JSON, and a
  truncated JSON object all return
  `RUNNER_STATUS_INVALID_JSON` with a single
  `DIAGNOSTIC_CODE_INVALID_JSON` diagnostic, an empty `patch_plan`,
  the legacy `error: "invalid_json"` string, and the mock-provider
  short-circuit markers preserved.
- `test_invalid_json_does_not_invoke_apply_phase` patches
  `apply_final_reconciliation_patch_plan` and asserts it is never
  called when the runner returns `invalid_json`. The on-disk target
  file is also unchanged.

This pins the
`accurate-ingest-final-reconciliation-patch-contract` Scenario
"Invalid JSON is rejected" and the
`accurate-ingest-final-json-validation-loop` validator contract.

### 2. Forbidden file edits / path traversal / source-middle artifacts (12 tests, `TestStep63ForbiddenTargetNegative`)

The validator
`validate_final_reconciliation_patch_targets(plan, brief)` is exercised
on the full set of forbidden-target classes from the design and
specs. Every violation is rejected with
`DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET`:

- `../unsafe.json` (path traversal)
- `/etc/passwd` (POSIX absolute)
- `C:/Windows/system32/config` (Windows drive)
- `..\\unsafe.json` (backslash)
- `source_graph.json` (source graph)
- `source_manifest.json` (source manifest)
- `normalized_packet.json` (normalized packet)
- `builder_blueprint.json` (blueprint)
- `builder_blueprint_report.json` (blueprint report)
- `MODULE_SUMMARY.md` (module summary)
- `accurate_ingest_audit_run/run.json` (backstage audit)
- `module_context.json` with editable_surfaces that do not include it
  (whitelist miss)

This pins the
`accurate-ingest-final-reconciliation-patch-contract` Scenario
"Forbidden file target is rejected" and the
`accurate-ingest-llm-builder-final-editorial-pass` Scenario "Source
artifacts remain unchanged".

### 3. Runtime-only target edits (9 tests, `TestStep63RuntimeOnlyTargetNegative`)

End-to-end through both the apply helper
`apply_final_reconciliation_patch_plan` AND the combined orchestrator
`apply_validate_and_gate_final_reconciliation_patch_plan`:

- `module_plot.json` (rejected, file untouched, gates not invoked)
- `party_tracker.json` (rejected, file untouched)
- `areas/lidda_start.json` live (rejected, file untouched, even when
  the brief lists `areas/` as an editable surface)
- `player_quests_lidda.json` (rejected, file untouched)
- `encounters/encounter_42.json` (rejected, file untouched)
- `modules/world_registry.json` (rejected, file untouched)
- `modules/campaign.json` (rejected, file untouched)
- Combined orchestrator on `module_plot.json` and `party_tracker.json`
  to prove the gate helpers are not invoked and
  `gates.status == "not_run"`.

This pins the
`accurate-ingest-final-reconciliation-patch-contract` Scenario
"Forbidden file target is rejected" and the design Decision 3
"Patch application is Python-gated".

### 4. False clean source-fidelity claims (5 tests, `TestStep63FalseCleanSourceFidelityNegative`)

- `run_llm_final_editor(mock_provider_output=...)` rejects every
  clean-pass variant (`pass`, `clean_pass`, `clean`,
  `source_fidelity_pass`) with
  `RUNNER_STATUS_INVALID_PATCH_CONTRACT` and
  `DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM`. Missing or
  non-string claim values are also rejected.
- `apply_final_reconciliation_patch_plan` rejects a `clean_pass` claim
  with `FINAL_RECONCILIATION_APPLY_STATUS_FAILED`, the same
  diagnostic, zero `changed_files`, and the on-disk target file
  unchanged.
- `build_accepted_final_reconciliation_report` always normalizes
  `source_fidelity_effective_status` to `reconciled_degraded` on
  the accepted path, even if the patch plan carries a clean-pass
  claim (this is the source-fidelity-honesty contract; the report
  must NEVER lock a clean source fidelity pass).

This pins the
`accurate-ingest-final-reconciliation-patch-contract` Scenario
"False clean source-fidelity claim is rejected" and the
`accurate-ingest-final-reconciliation-reporting` Scenario "Accepted
reconciliation report is persisted".

### 5. Provider unavailable (3 tests, `TestStep63ProviderUnavailableNegative`)

- `create_chat_client` raising returns `RUNNER_STATUS_PROVIDER_FAILED`
  with `DIAGNOSTIC_CODE_PROVIDER_FAILED`; the legacy `error` field
  carries the underlying cause.
- `client.chat.completions.create` raising returns the same
  `RUNNER_STATUS_PROVIDER_FAILED` with the same diagnostic; legacy
  `error` field carries the underlying cause.
- The apply helper is never invoked on this path; the runner
  surfaces a clean fail-closed outcome without writing any file.

This pins the
`accurate-ingest-llm-builder-final-editorial-pass` Scenario "Provider
failure fails closed".

### 6. Fatal/mixed classification overrides accepted report on disk (2 tests added to `TestStep53FatalMixedGuard` in `scripts/test_toolkit_homebrew_gui_unified_flow.py`)

- `test_fatal_classification_overrides_accepted_report_on_disk`:
  Writes a synthetic `final_reconciliation_report.json` on disk
  (status=accepted, `reconciled_degraded`, playable candidate true)
  before the build runs, then drives the packet builder with a
  fatal classification. The editor is never invoked, the build
  remains `status: blocked, stage: build_fidelity, error:
  build_fidelity_blocked:...`, no
  `final_reconciliation_required` / `final_reconciliation_accepted` /
  `source_fidelity_effective_status` fields appear, and the on-disk
  accepted report is preserved untouched (a fatal outcome must not
  silently rewrite or delete it).
- `test_mixed_classification_overrides_accepted_report_on_disk`:
  Same contract for a mixed classification (fatal + editorial
  blockers). The editor is never invoked, the build remains
  blocked, and the on-disk accepted report is preserved.

This pins the Step 5.3 source contract test class's existing
behavior at the spec-required negative-assertion level.

## Production change (small, contract-required)

The new
`test_blueprint_artifact_rejected_by_targets` /
`test_blueprint_report_artifact_rejected_by_targets` tests exposed a
real contract gap in the
`_FORBIDDEN_SOURCE_MIDDLE_PATTERNS` constant. The previous pattern
`"blueprint_*.json"` did NOT match the production filenames
`builder_blueprint.json` and `builder_blueprint_report.json` because
`fnmatch.fnmatch('builder_blueprint.json', 'blueprint_*.json')`
returns `False` (the `*` does not span the `builder_` prefix). A
false-positive patch targeting the production blueprint artifacts
would have violated the
`accurate-ingest-llm-builder-final-editorial-pass` Scenario "Source
artifacts remain unchanged".

The pattern is updated to `"*blueprint*.json"` in
`utils/toolkit_llm_final_reconciliation.py` with a comment
documenting the fix. The pattern now matches the production
filenames AND the existing
`test_rejects_blueprint_glob` test (which uses
`blueprint_v2.json`). No other tests or production code is changed.

The fix is also asserted by:

- `test_blueprint_artifact_rejected_by_targets`
  (builder_blueprint.json)
- `test_blueprint_report_artifact_rejected_by_targets`
  (builder_blueprint_report.json)
- The pre-existing `test_rejects_blueprint_glob` (blueprint_v2.json)

## Files modified

- `scripts/test_toolkit_llm_final_reconciliation.py` (new test
  classes: `TestStep63InvalidJsonNegative` (5 tests),
  `TestStep63ProviderUnavailableNegative` (3 tests),
  `TestStep63ForbiddenTargetNegative` (12 tests),
  `TestStep63RuntimeOnlyTargetNegative` (9 tests),
  `TestStep63FalseCleanSourceFidelityNegative` (5 tests); total 34
  new tests; all 558 tests in the file pass).
- `scripts/test_toolkit_homebrew_gui_unified_flow.py` (2 new
  helper methods + 2 new test methods added to
  `TestStep53FatalMixedGuard`; the class now has 9 tests, all pass).
- `utils/toolkit_llm_final_reconciliation.py` (1-line production
  fix: `_FORBIDDEN_SOURCE_MIDDLE_PATTERNS` `blueprint_*.json` ->
  `*blueprint*.json`, with a docstring comment documenting the
  contract gap).
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`
  (Step 6.3 checked; 6.4 and Section 7 left untouched).
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-6-3-negative-tests.md`
  (this file).

## Verification

- `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py scripts/test_toolkit_homebrew_gui_unified_flow.py` -> PASS
- `.venv/bin/python -m unittest -q scripts.test_toolkit_llm_final_reconciliation` -> **558 PASS, 0 FAIL** (was 524; +34 new)
- `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep53FatalMixedGuard scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation` -> **18 PASS, 0 FAIL** (Step 5.1 + Step 5.3 expanded test classes)
- `.venv/bin/python -m unittest -q scripts.test_file_operations_path_safety scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_toolkit_llm_final_reconciliation` -> **661 PASS, 0 FAIL** (all related suites green)
- `python3 scripts/check_ascii_compliance.py scripts/test_toolkit_llm_final_reconciliation.py scripts/test_toolkit_homebrew_gui_unified_flow.py` -> `0 violations`
- `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
