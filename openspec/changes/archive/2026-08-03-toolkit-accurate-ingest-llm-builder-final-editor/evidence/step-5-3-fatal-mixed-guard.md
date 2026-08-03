# Step 5.3: Fatal / Mixed Blocker Guard

**Status:** COMPLETED 2026-06-12

## Objective

Pin the contract that fatal and mixed `final_blocker_classification` outcomes
remain fail-closed and never invoke the LLM Builder final editor. The existing
Step 4.2 terminal block (`if not _is_final_reconciliation: ...`) already
satisfies this; this step adds explicit provider-free tests and a short
clarifying comment so a future regression that hoists the editor call out of
the editorial branch is immediately caught.

The Step 5.3 contract:

- Fatal classification -> `status: blocked, stage: build_fidelity, error: build_fidelity_blocked:...`,
  no `final_reconciliation_required`, no `final_reconciliation_accepted`,
  no `source_fidelity_effective_status`, fatal diagnostics remain visible in
  `final_blocker_classification` / `build_fidelity`. Editor NOT invoked.
- Mixed classification (both fatal and editorial blockers present) -> same
  blocked outcome as fatal. The `fatal_blockers` list is preserved on the
  classification so downstream reports can surface the fatal diagnostics.
  Editor NOT invoked.
- The structural source contract: `_invoke_final_editor_or_fallback(...)` and
  `from utils.toolkit_llm_final_reconciliation import ...` are confined to
  the `if _cls_status == "editorial":` branch and the helper function that
  contains them. No fatal / mixed / unknown branch can reach the editor.

## Files Changed

### Production code (comment only, no behavior change)

- `web/extensions/toolkit_homebrew_packet_builder.py`
  - Replaced the 1-line comment `# Step 4.2: fatal/mixed/unknown -> terminal block`
    above the `if not _is_final_reconciliation:` guard with a 5-line clarifying
    block that documents the Step 5.3 contract:
    - The final editor (and the helper that invokes it) is reached ONLY
      through the `if _cls_status == "editorial":` branch.
    - The `if not _is_final_reconciliation:` guard catches everything else
      and keeps the build blocked at the build_fidelity layer.
    - No editor invocation, no reconciliation fields set on fatal/mixed/unknown.
  - No code logic was changed. The guard, the build_result mutations, and
    the surrounding flow are byte-for-byte unchanged.

### Tests

- `scripts/test_toolkit_homebrew_gui_unified_flow.py`
  - Added new test class `TestStep53FatalMixedGuard` (7 tests, all
    provider-free via `unittest.mock.patch`):
    1. `test_fatal_keeps_blocked_state_no_editor_invocation` -- end-to-end
       run: fatal classification -> blocked at build_fidelity, no editor
       call, no `final_reconciliation_required` /
       `final_reconciliation_accepted` / `source_fidelity_effective_status`,
       fatal diagnostics remain visible in `final_blocker_classification`
       and `build_fidelity`.
    2. `test_mixed_keeps_blocked_state_no_editor_invocation` -- end-to-end
       run: mixed classification (1 fatal + 2 editorial blockers) -> same
       blocked outcome, no editor call, no reconciliation fields.
    3. `test_mixed_preserves_fatal_blockers_in_classification` -- mixed
       classification preserves BOTH `fatal_blockers` (1 entry) and
       `editorial_blockers` (2 entries) lists on the build_result. The
       `final_blocker_classification_status` field is set to `"mixed"`.
    4. `test_fatal_does_not_set_source_fidelity_effective_status` -- fatal
       path must not emit any `source_fidelity_effective_status` value at
       all (the field is absent in both `result` and `result["build_fidelity"]`).
       Even in a regression, the value must not match any clean-pass
       variant (`"pass"`, `"clean_pass"`, `"clean"`, `"source_fidelity_pass"`).
    5. `test_source_contract_editorial_only_branch_invokes_helper` -- source
       contract via `inspect.getsource`: the `_invoke_final_editor_or_fallback(...)`
       call site sits AFTER an `if _cls_status == "editorial":` opener, and
       no `if _cls_status == "fatal":`, `"mixed":`, or `"unknown":` opener
       appears between that editorial branch and the call site.
    6. `test_source_contract_helper_api_import_inside_editorial_branch` --
       source contract: `from utils.toolkit_llm_final_reconciliation import ...`
       lives inside `_invoke_final_editor_or_fallback` and is wrapped in
       `try/except` (the editorial-only helper by construction; the previous
       test guarantees the helper is only called from the editorial branch).
    7. `test_source_contract_fatal_block_guarded_by_negation` -- source
       contract: the `if not _is_final_reconciliation:` guard exists and
       the block it protects sets the canonical `build_fidelity_blocked:`
       error with `status: "blocked"` and `stage: "build_fidelity"`.

## Verification

- `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py scripts/test_toolkit_homebrew_gui_unified_flow.py` -> PASS
- `.venv/bin/python -m unittest -v scripts.test_toolkit_homebrew_gui_unified_flow.TestStep53FatalMixedGuard` -> **7 PASS, 0 FAIL**
- `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep42FatalBlockedBehavior scripts.test_toolkit_homebrew_gui_unified_flow.TestStep43EditorialReconciliationRequired scripts.test_toolkit_homebrew_gui_unified_flow.TestStep44AcceptedReconciliation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep45EvidenceReportsImmutability scripts.test_toolkit_homebrew_gui_unified_flow.TestStep46PackBuilderEditorialBranch scripts.test_toolkit_homebrew_gui_unified_flow.TestStep53FatalMixedGuard` -> **42 PASS, 0 FAIL** (35 prior step 4.x/5.1/5.2 + 7 new step 5.3)
- `.venv/bin/python -m unittest -q scripts.test_toolkit_llm_final_reconciliation` -> **524 PASS, 0 FAIL** (no regression on final-reconciliation runner)
- `.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity` -> **135 PASS, 0 FAIL** (no regression on publication parity)
- `python3 scripts/check_ascii_compliance.py scripts/test_toolkit_homebrew_gui_unified_flow.py web/extensions/toolkit_homebrew_packet_builder.py` -> **0 violations**
- `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID

## Contract Pinned

- Fatal classification -> `status: blocked, stage: build_fidelity, error: build_fidelity_blocked:...`, no editor invocation, no reconciliation fields, fatal diagnostics remain visible to downstream consumers.
- Mixed classification -> same blocked outcome as fatal; both `fatal_blockers` and `editorial_blockers` lists preserved on the classification payload.
- The final editor (`_invoke_final_editor_or_fallback`) and its helper-API import (`from utils.toolkit_llm_final_reconciliation import ...`) are STRUCTURALLY confined to the editorial branch. A regression that hoists either out of the editorial branch is caught immediately by source-contract tests.
- Unknown classification (no editor invocation possible) continues to fall through the same `if not _is_final_reconciliation:` guard. The Step 5.1 `test_editorial_unknown_classification_does_not_invoke_editor` test remains the source-of-truth for the unknown path; this step adds no duplicate coverage.

## Out of Scope (Step 5.4+)

- Front/middle pipeline artifacts: untouched. Step 5.4 will add source-contract tests proving no reconciliation fields enter source graph, normalized packet, blueprint, backstage audit, or ModuleBuilder handoff.
- No new tests for `build_blocked_final_reconciliation_report` (already covered by Step 4.5 in `scripts/test_toolkit_llm_final_reconciliation.py`, 524 tests).
- The 8 pre-existing errors in `scripts.test_toolkit_homebrew_gui_unified_flow` (in `TestDescribeBlueprintNotReady` and `TestPacketBuilderV2Integration`) are pre-existing failures from earlier steps and are NOT caused by Step 5.3 changes. The new `TestStep53FatalMixedGuard` class sits in the same file and does not interact with those tests.
