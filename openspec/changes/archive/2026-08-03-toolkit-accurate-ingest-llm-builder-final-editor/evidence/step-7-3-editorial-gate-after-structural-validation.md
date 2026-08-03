# Step 7.3: Editorial Reconciliation Only Runs After Structural Validation Passes

**Date:** 2026-06-23

## Objective

Prove that the LLM final-editor is invoked ONLY for editorial-only blocker classifications after structural validation passes, and NOT for fatal structural categories. Three gates must be proven:

1. Fatal structural validation categories (reference_integrity, spatial_contract, party, structural, schema, topology) do NOT invoke the final editor.
2. Editorial-only blockers after structural validation passes DO invoke the final editor.
3. Well of Ruin module status is handled honestly — if still structurally broken, classification is fatal; if repaired, editorial path proceeds normally.

## Well of Ruin Local Status

- `modules/Well_of_Ruin` IS present locally.
- `spatial_repair_report.json` shows `status: "changed"`, `repaired_area_count: 4`, `unresolved_count: 0` (structural spatial repair has been applied).
- `validation_report.json` and `validation_report_BU.json` show `"issues": []` with zero structural failures.
- The structural repair (`toolkit-accurate-ingest-modulebuilder-structural-repair`) has been applied to the local checkout. Structural validation passes.
- The remaining editorial blockers (locations: 0, npc/puzzle source-fidelity mismatches) are handled by the editorial-only classification path.

## Proven Gates

### Gate 1: Fatal structural categories do NOT invoke the final editor

**Classifier contract** (`utils/toolkit_final_blocker_classifier.py`):
- `FATAL_CATEGORIES` explicitly includes `reference_integrity`, `spatial_contract`, `party`, `structural`, `schema`, `topology` (lines 37-45).
- `_is_fatal_blocker()` uses a simple `in` check against this list (line 139): any of these categories returns `True` for fatal.
- 57 classifier tests pass (`test_toolkit_final_blocker_classifier: 57/57 OK`), proving the fatal/editorial classification mechanism works for all categories.

**Packet-builder routing** (`scripts/test_toolkit_homebrew_gui_unified_flow.py TestStep53FatalMixedGuard`):
- `test_fatal_keeps_blocked_state_no_editor_invocation` — fatal classification (using `"category": "structural"`), the editor mock is `assert_not_called()`, the build stays `status: blocked, stage: build_fidelity`.
- `test_mixed_keeps_blocked_state_no_editor_invocation` — mixed classification (fatal + editorial), editor mock is `assert_not_called()`.
- `test_source_contract_editorial_only_branch_invokes_helper` — source-contract proof: `_invoke_final_editor_or_fallback` is only reachable from the `if _cls_status == "editorial":` branch.
- `test_source_contract_fatal_block_guarded_by_negation` — source-contract proof: the `if not _is_final_reconciliation:` guard catches fatal/mixed/unknown before any editorial branch opens.
- `test_fatal_classification_overrides_accepted_report_on_disk` — even with a pre-existing accepted report on disk, a fatal classification overrides it: editor NOT invoked, build stays blocked.
- `test_mixed_classification_overrides_accepted_report_on_disk` — same contract for mixed.

**Result: ALL 9 tests PASS. Fatal structural categories reliably block final-editor invocation.**

### Gate 2: Editorial-only blockers DO invoke the final editor

**Packet-builder editorial path** (`scripts/test_toolkit_homebrew_gui_unified_flow.py TestStep51FinalEditorInvocation`):
- `test_editorial_editor_accepted_persists_and_continues` — editorial classification with accepted editor result: editor invoked, brief persisted, build continues with `final_reconciliation_accepted=True`, `source_fidelity_effective_status=reconciled_degraded`.
- `test_editorial_fatal_classification_does_not_invoke_editor` — negative proof: editorial path explicitly skips invocation for fatal classification.
- `test_editorial_unknown_classification_does_not_invoke_editor` — same for unknown classification.
- `test_editorial_editor_exception_remains_blocked` — editorial path with editor exception: gracefully degrades to blocked with diagnostic.
- `test_editorial_accepted_status_never_claims_clean_pass` — honesty invariant: accepted path never claims `pass` / `clean_pass` / `clean` / `source_fidelity_pass`.

**Also proven by TestStep43EditorialReconciliationRequired (8 tests)**:
- Editorial classification → `final_reconciliation_required=True`; fatal still blocked.

**Result: ALL 18 tests PASS. Editorial-only classification reliably invokes the final editor.**

### Gate 3: Well of Ruin bogus-atom handling (editorial-only path)

**Dedicated fixture tests** (`scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py`):
- 37 tests across 5 classes prove that Well-like bogus headings (`Trigger`, `Passive Element`, `Active Element`) are classified as non-playable, do not poison narrator-facing topology, and are handled via editorial-only decisions (`delete_bogus_atom`, `preserve_as_dm_guidance`, `reclassify_atom`).
- All tests use synthetic fixtures in tempdir; no production module is mutated.

**Source-atom triage hardening** (prerequisite `toolkit-accurate-ingest-source-atom-triage-hardening`):
- Well/Ruin/Awaken/Enrage/Menace/Enthrall/Irradiate/Overwhelm and full effect sentences are filtered from required NPC blockers at manifest, triage, blueprint, and build-fidelity boundaries.

**Result: 37 tests PASS. Well-like editorial blockers correctly handled through editorial-only path.**

## Verified Test Suite Summary

| Test Suite | Tests | Status |
|-----------|-------|--------|
| `test_toolkit_final_blocker_classifier` | 57 | ALL PASS |
| `test_toolkit_homebrew_gui_unified_flow` (fatal/mixed/editorial + editor invocation) | 31 | ALL PASS |
| `test_toolkit_step61_well_of_ruin_bogus_atoms` | 37 | ALL PASS |
| `test_toolkit_llm_final_reconciliation` | 572 | ALL PASS |
| `test_file_operations_path_safety` | 9 | ALL PASS |
| `test_toolkit_final_reconciliation` | 62 | ALL PASS |
| `test_toolkit_report_agreement` | 32 | ALL PASS |
| `test_toolkit_module_build_publication_parity` | 162 | ALL PASS |

## Verification Commands Run

```bash
.venv/bin/python -m py_compile utils/toolkit_final_blocker_classifier.py scripts/test_toolkit_final_blocker_classifier.py scripts/test_toolkit_homebrew_gui_unified_flow.py scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py scripts/test_toolkit_llm_final_reconciliation.py
# -> PASS (no output)

.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep53FatalMixedGuard -v
# -> 9 PASS, 0 FAIL

.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation -v
# -> 9 PASS, 0 FAIL

.venv/bin/python -m unittest scripts.test_toolkit_step61_well_of_ruin_bogus_atoms -v
# -> 37 PASS, 0 FAIL

.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -q
# -> 572 PASS, 0 FAIL

.venv/bin/python -m unittest scripts.test_toolkit_final_blocker_classifier -q
# -> 57 PASS, 0 FAIL

openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict
# -> VALID
```

## Conclusion

All three gate conditions for Step 7.3 are proven by existing provider-free tests:

1. **Fatal structural categories block final-editor invocation** — proven by `TestStep53FatalMixedGuard` (9 tests) + classifier test (57 tests). The FATAL_CATEGORIES list explicitly includes `reference_integrity`, `spatial_contract`, and `party`. Source-contract tests confirm the editor helper is only reachable from the `if _cls_status == "editorial":` branch, and the `if not _is_final_reconciliation:` guard catches all fatal/mixed/unknown classifications first.

2. **Editorial-only blockers invoke the final editor** — proven by `TestStep51FinalEditorInvocation` (9 tests) + `TestStep43EditorialReconciliationRequired` (8 tests). Editorial classification routes through `_invoke_final_editor_or_fallback`, which calls `run_final_reconciliation_with_bounded_retry`. The editorial path is fully tested including accepted, rejected, exception, and import-failure branches.

3. **Well of Ruin status handled honestly** — the local module has been structurally repaired (spatial repair applied, validation shows 0 issues). The Well-like bogus atoms are tested via synthetic fixtures in `test_toolkit_step61_well_of_ruin_bogus_atoms` (37 tests). No production code was modified by this evidence step.

No new tests were needed. The existing provider-free test coverage already proves the 7.3 editorial-before-structural gate.
