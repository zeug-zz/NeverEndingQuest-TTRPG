# Step 3.3 Evidence: Source-Fidelity-Claim Validation

Date: 2026-06-12

## 1. Files Added

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-3-3-source-fidelity-claim-validation.md` (this file)

## 2. Files Modified

- `utils/toolkit_llm_final_reconciliation.py` (~230 lines added: 1 new diagnostic code, 1 new accepted-claim constant, 1 new clean-pass-variants tuple, 1 private `_is_clean_pass_claim` helper, 1 main `validate_final_reconciliation_source_fidelity_claim` helper, 1 runner wiring helper `_apply_source_fidelity_claim_validation_to_runner_status`, and 2 call-site updates in `run_llm_final_editor`)
- `scripts/test_toolkit_llm_final_reconciliation.py` (~640 lines added: 5 new imports, 1 new fixture `_ready_plan_with_source_fidelity_claim`, 4 new test classes `TestSourceFidelityClaimConstants` (3 tests), `TestIsCleanPassClaim` (5 tests), `TestValidateFinalReconciliationSourceFidelityClaim` (26 tests), `TestRunnerSourceFidelityClaimWiring` (11 tests))
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 3.3 checked off with completion evidence)

## 3. Files Read (Context)

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/proposal.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/design.md` (Decision 4: Source fidelity remains honest)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 1.x, 2.x, 3.1, 3.2 evidence)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-final-reconciliation-patch-contract/spec.md` (false clean source-fidelity claim scenario)
- `prompts/toolkit/final_reconciliation_builder_prompt.txt` (lines 87-91: source-fidelity claim honesty rule; lines 219-243: refused example with `source_fidelity_claim: reconciled_degraded`; lines 245-265: failed example with `source_fidelity_claim: reconciled_degraded`)
- `utils/toolkit_final_reconciliation.py` (`source_fidelity_effective_status: reconciled_degraded` contract)
- `utils/toolkit_llm_final_reconciliation.py` (Step 2.4 / 3.1 / 3.2 runner scaffold, contract helper, target validation wiring)
- `scripts/test_toolkit_llm_final_reconciliation.py` (Step 2.4 / 3.1 / 3.2 test scaffold)

## 4. Public Surface

### Constants (newly exported)

- `FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED = "reconciled_degraded"` (the only accepted claim for ready plans)
- `FINAL_RECONCILIATION_SOURCE_FIDELITY_CLEAN_PASS_VARIANTS = ("pass", "clean_pass", "clean", "source_fidelity_pass")` (forbidden variants to catch LLM drift to equivalent clean-pass language)
- `DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM = "invalid_source_fidelity_claim"`

### Module-internal constants (not exported)

- `_EXPECTED_ACCEPTED_CLAIM = FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED` (used in diagnostic messages so reports can show the expected value)

### New helper functions

Pure, no mutation, no filesystem, no provider:

- `_is_clean_pass_claim(value)` -> bool (exact-match detection against the forbidden variants)
- `validate_final_reconciliation_source_fidelity_claim(patch_plan, brief) -> (bool, diagnostics)` - main helper enforcing the strict `reconciled_degraded` claim for ready plans and surfacing false clean claims for refused/failed plans
- `_apply_source_fidelity_claim_validation_to_runner_status(parser_status, parser_diagnostics, patch_plan, brief) -> (status, diagnostics)` - runner wiring helper that escalates ready-plan failures to `RUNNER_STATUS_INVALID_PATCH_CONTRACT` while preserving refused/failed semantics

## 5. Behavior

### Validation rules (in declared order)

1. `patch_plan` MUST be a `dict`. A non-dict plan is rejected with a single `invalid_source_fidelity_claim` diagnostic.
2. `brief` MUST be a `dict`. A non-dict brief is rejected with a single `invalid_source_fidelity_claim` diagnostic.
3. When the top-level `status` is not one of `ready` / `refused` / `failed`, the helper returns `(True, [])` so the contract helper (Step 3.1) can emit its own `unsupported_status` diagnostic without a confusing duplicate.
4. When `status: ready`:
   - `source_fidelity_claim` MUST be present
   - `source_fidelity_claim` MUST be a string
   - `source_fidelity_claim` MUST equal `reconciled_degraded` EXACTLY
   - Any value in the clean-pass variant tuple is rejected as a false clean claim
   - `is_valid` is False if any of the above fails
5. When `status: refused` or `status: failed`:
   - Refused/failed semantics are PRESERVED. `is_valid` remains True.
   - If the claim is a known clean-pass variant, a diagnostic is appended so downstream reports can surface the false claim without flipping the runner status.

### Reused status decision

`RUNNER_STATUS_INVALID_PATCH_CONTRACT` is reused for the runner-level fail-closed outcome. This is consistent with Steps 3.1 and 3.2 and keeps the runner status enum tight. Downstream reports key on the diagnostic code (`invalid_source_fidelity_claim`) rather than the runner status, so the aggregation is intentionally consistent.

### Why `reconciled_degraded` is the only accepted claim

Per the archived boundary contract (`utils/toolkit_final_reconciliation.py`, `build_final_reconciliation_report(...)`):

- When `classification_status == "editorial"` AND reconciliation is accepted, `source_fidelity_effective_status` is set to `"reconciled_degraded"`.
- The LLM's `source_fidelity_claim` MUST match the effective status, because the report cannot claim playable publication with a clean source-fidelity pass when the original source fidelity was blocked or degraded.

## 6. Forbidden clean-pass variants

The variant tuple intentionally catches LLM drift to equivalent clean-pass language:

- `"pass"` - the most direct equivalent
- `"clean_pass"` - the prompt-declared forbidden term
- `"clean"` - shorter equivalent
- `"source_fidelity_pass"` - explicit source-fidelity claim

Case-sensitive: `"PASS"`, `"Clean_Pass"`, etc. are NOT recognized as clean-pass claims and would surface in the generic "not equal to reconciled_degraded" branch with `invalid_source_fidelity_claim` diagnostic.

## 7. Test Coverage

- `TestSourceFidelityClaimConstants` (3 tests) - pins the accepted-claim value, the clean-pass variant tuple, and the diagnostic code.
- `TestIsCleanPassClaim` (5 tests) - exact-match detection: known variants return True; the accepted claim, case variants, non-strings, and empty string return False.
- `TestValidateFinalReconciliationSourceFidelityClaim` (26 tests) - accept/reject cases for ready plans, all four clean-pass variants, missing/non-string claims, case-variant rejection, refused/failed plan semantics (preserved status with diagnostic on false clean claim, no diagnostic on accepted claim), defensive input handling (non-dict plan / non-dict brief / unsupported status), and purity (no mutation of plan or brief on success or failure paths, error severity on diagnostics).
- `TestRunnerSourceFidelityClaimWiring` (11 tests) - end-to-end runner-level tests through `mock_provider_output`:
  - `test_runner_ready_with_reconciled_degraded_claim_returns_success` - success path
  - `test_runner_ready_with_pass_claim_fails_closed` - the headline Step 3.3 behavior
  - `test_runner_ready_with_clean_pass_claim_fails_closed` - prompt-declared forbidden term
  - `test_runner_ready_with_clean_claim_fails_closed` - shorter equivalent
  - `test_runner_ready_with_source_fidelity_pass_claim_fails_closed` - explicit source-fidelity claim
  - `test_runner_ready_with_missing_claim_fails_closed` - layered with parse gate; expects either `missing_required_keys` or `invalid_patch_contract`
  - `test_runner_ready_with_integer_claim_fails_closed` - non-string claim
  - `test_runner_refused_with_clean_pass_claim_preserves_refused_status` - refused preserved with diagnostic
  - `test_runner_failed_with_clean_pass_claim_preserves_failed_status` - failed preserved with diagnostic
  - `test_runner_refused_with_reconciled_degraded_claim_preserves_refused_status` - no diagnostic for clean refused plan
  - `test_runner_does_not_call_live_provider_under_fidelity_failure` - mock short-circuit preserved
  - `test_runner_does_not_call_live_provider_under_fidelity_success` - mock short-circuit on success

## 8. Verification

- `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
- `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **230 PASS, 0 FAIL** in 0.010s (was 185, +45)
- `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **106/106 OK** in 0.089s (no regression in dependent suites)
- `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
- `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
- `openspec validate --specs` -> 364/364 PASS (no spec regression)

## 9. Scope Confirmation

- No live provider call in tests: confirmed (mock_provider_output short-circuit, all 230 tests pass without network).
- No packet-builder integration: confirmed (no edits to `web/extensions/toolkit_homebrew_packet_builder.py` or any other packet-builder file in this step).
- No patch application: confirmed (the runner does not write files; Step 3.4 is reserved for patch application).
- No report persistence: confirmed (no call to `persist_final_reconciliation_report(...)` from the runner; Step 4.4 is reserved for report persistence).
- No schema/readiness/publishability gates: confirmed (no call to `validate_module_files.py` or any readiness/publishability helper from the runner; Section 4 is reserved for the validation loop).
- ASCII-only: confirmed (0 violations across both files).
- No mutation of inputs: confirmed (helper-level and runner-level purity tests cover this).
