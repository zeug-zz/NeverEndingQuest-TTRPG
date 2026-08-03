# Step 3.1 Evidence: Final Reconciliation Patch Contract and Allowed Decision Types

Date: 2026-06-11

## 1. Files Added

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-3-1-patch-contract.md` (this file)

## 2. Files Modified

- `utils/toolkit_llm_final_reconciliation.py` (~210 lines added: 6 decision-type constants, 1 allowed-types tuple, 1 new runner status, 6 new diagnostic codes, 1 new helper function `validate_final_reconciliation_patch_contract`, wiring into `_parse_runner_response`, and an error-message mapper branch for the new status)
- `scripts/test_toolkit_llm_final_reconciliation.py` (~520 lines added: 2 new test classes `TestPatchContractValidation` and `TestPatchContractWiringInParseAndRunner`, updated imports, 33 new tests)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 3.1 checked off with completion evidence)

## 3. Files Read (Context)

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/proposal.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/design.md` (Patch Contract section)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Steps 1-2.4 evidence + Step 3.1)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-final-reconciliation-patch-contract/spec.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-bogus-source-atom-cleanup/spec.md`
- `utils/toolkit_llm_final_reconciliation.py` (Step 2.4 runner)
- `scripts/test_toolkit_llm_final_reconciliation.py` (Step 2.4 test scaffold)
- `prompts/toolkit/final_reconciliation_builder_prompt.txt` (allowed decision types and patch version pin)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-2-4-fail-closed-diagnostics.md` (Step 2.4 evidence)

## 4. Public Surface

### Constants (newly exported)

Allowed decision types (each is an individual constant; the tuple is the
source of truth and is also exported for tests and downstream consumers):

- `FINAL_RECONCILIATION_DECISION_DELETE_BOGUS_ATOM` -- `"delete_bogus_atom"`
- `FINAL_RECONCILIATION_DECISION_RECLASSIFY_ATOM` -- `"reclassify_atom"`
- `FINAL_RECONCILIATION_DECISION_MERGE_INTO_EXISTING` -- `"merge_into_existing"`
- `FINAL_RECONCILIATION_DECISION_PRESERVE_AS_DM_GUIDANCE` -- `"preserve_as_dm_guidance"`
- `FINAL_RECONCILIATION_DECISION_CREATE_MISSING_REAL_ELEMENT` -- `"create_missing_real_element"`
- `FINAL_RECONCILIATION_DECISION_REFUSE` -- `"refuse"`
- `FINAL_RECONCILIATION_ALLOWED_DECISION_TYPES` -- the exact tuple above
  in design/prompt order, exported as the canonical allowlist.

New runner status (new fail-closed branch for contract violations):

- `RUNNER_STATUS_INVALID_PATCH_CONTRACT` -- `"invalid_patch_contract"`.
  Returned by the runner when the LLM returned `status: ready` but the
  patch plan violates one of the Step 3.1 shape rules.

New diagnostic codes (added to the existing `DIAGNOSTIC_CODE_*` group):

- `DIAGNOSTIC_CODE_INVALID_PATCH_CONTRACT` -- `"invalid_patch_contract"`
- `DIAGNOSTIC_CODE_UNSUPPORTED_VERSION` -- `"unsupported_version"`
- `DIAGNOSTIC_CODE_UNSUPPORTED_STATUS` -- `"unsupported_status"`
- `DIAGNOSTIC_CODE_INVALID_DECISIONS` -- `"invalid_decisions"`
- `DIAGNOSTIC_CODE_INVALID_FILE_PATCHES` -- `"invalid_file_patches"`
- `DIAGNOSTIC_CODE_UNSUPPORTED_DECISION_TYPE` -- `"unsupported_decision_type"`

### Function (newly exported for tests and downstream steps)

- `validate_final_reconciliation_patch_contract(patch_plan) -> (is_valid, diagnostics)`
  - Pure, read-only helper. Returns `is_valid=True` only when every
    shape rule passes.
  - Reports every violation in a single pass; never short-circuits on
    the first violation.
  - Enforces the following shape rules:
    1. `patch_plan` MUST be a `dict`.
    2. `version` MUST equal `FINAL_RECONCILIATION_PATCH_VERSION`
       (the v1 pin from design/prompt).
    3. `status` MUST be one of `ready`, `refused`, `failed` (the
       three top-level statuses).
    4. `decisions` MUST be a `list`. Each entry MUST be a `dict`
       with a string `"decision"` key whose value is in
       `FINAL_RECONCILIATION_ALLOWED_DECISION_TYPES`.
    5. `file_patches` MUST be a `list`. List shape only;
       `file_patches[].path` and other target fields are owned by
       Step 3.2.

### Wiring (in-place)

- `_parse_runner_response(raw_text)` (Step 2.4 helper):
  - `status: ready` branch now runs the contract helper and returns
    `RUNNER_STATUS_SUCCESS` only when the contract helper passes.
    Otherwise returns `RUNNER_STATUS_INVALID_PATCH_CONTRACT` with the
    contract diagnostics.
  - `status: refused` branch now also runs the contract helper and
    appends any shape diagnostics to the existing `refused_reconciliation`
    diagnostic. The primary `refused_reconciliation` status is preserved.
  - `status: failed` branch now also runs the contract helper and
    appends any shape diagnostics to the existing `failed_reconciliation`
    diagnostic. The primary `failed_reconciliation` status is preserved.
  - Unknown / non-string `status` branches are unchanged (still return
    `RUNNER_STATUS_MISSING_REQUIRED_KEYS`).

- `_build_error_message_for_status(status, diagnostics)` (Step 2.4 helper):
  - Added a new branch for `RUNNER_STATUS_INVALID_PATCH_CONTRACT` that
    returns `"invalid_patch_contract: <aggregated messages>"` so the
    legacy `error` field on the runner result carries the same
    information as the structured `diagnostics` list, in a short
    ASCII-only form.

- `run_llm_final_editor(...)`: signature and result shape are unchanged
  (no new top-level fields). The new runner status
  `RUNNER_STATUS_INVALID_PATCH_CONTRACT` simply replaces the previous
  `RUNNER_STATUS_SUCCESS` outcome when a `status: ready` plan violates
  the contract.

## 5. Behavior Contract

### Contract validation rules (Step 3.1)

| Rule | Field | Type | Reject when |
|------|-------|------|-------------|
| 1 | `patch_plan` | `dict` | not a `dict` |
| 2 | `version` | `str` | not equal to `FINAL_RECONCILIATION_PATCH_VERSION` |
| 3 | `status` | `str` | not in `{ready, refused, failed}` |
| 4a | `decisions` | `list` | not a `list` |
| 4b | each `decisions[i]` | `dict` | not a `dict` |
| 4c | each `decisions[i]` | `dict` | missing `"decision"` key |
| 4d | `decisions[i]["decision"]` | `str` | not a `string` |
| 4e | `decisions[i]["decision"]` | `str` | not in `FINAL_RECONCILIATION_ALLOWED_DECISION_TYPES` |
| 5 | `file_patches` | `list` | not a `list` |

Diagnostics on rejection:

- Rule 1 -> `invalid_patch_contract` (single diagnostic; return False
  immediately, do not inspect further).
- Rules 2, 3, 4a, 4b, 4c, 4d, 5 -> the diagnostic code named in the
  rule (single diagnostic per violation, all reported in one pass).
- Rule 4e -> `unsupported_decision_type` (different code so downstream
  reports can distinguish "shape violation" from "out-of-allowlist
  decision value").

### Status mapping in `_parse_runner_response` (after Step 3.1)

| Input | `status` | `error` |
|-------|----------|---------|
| `status: ready` + contract passes | `RUNNER_STATUS_SUCCESS` | `None` |
| `status: ready` + contract fails | `RUNNER_STATUS_INVALID_PATCH_CONTRACT` | `"invalid_patch_contract: <messages>"` |
| `status: refused` (regardless of contract) | `RUNNER_STATUS_REFUSED_RECONCILIATION` | `"refused_reconciliation"` (+ contract diagnostics in `diagnostics`) |
| `status: failed` (regardless of contract) | `RUNNER_STATUS_FAILED_RECONCILIATION` | `"failed_reconciliation"` (+ contract diagnostics in `diagnostics`) |

The refused/failed branches continue to fail closed with their
respective primary statuses (Step 2.4 contract). Contract diagnostics
are appended to the diagnostic list so downstream reports can show
shape issues alongside the refusal/failure.

### Out of scope (Step 3.1 explicitly defers)

- File target / path validation: Step 3.2. The contract helper
  inspects only `file_patches` list shape; `file_patches[].path`,
  `file_patches[].operations`, and any other target field are not
  inspected. A test in this step
  (`test_file_patches_path_contents_pass_in_step_3_1_step_3_2_will_reject`)
  asserts that a ready plan with `file_patches: [{"path": "../unsafe.json", ...}]`
  PASSES Step 3.1 (because only list shape is checked) and the test
  name is explicit so Step 3.2 can update the assertion.
- Source-fidelity claim validation: Step 3.3. A `status: ready` plan
  with `source_fidelity_claim: "pass"` still passes the contract helper
  because Step 3.1 only checks shape. The "false clean source-fidelity
  claim" guard is owned by Step 3.3.
- Patch application: Step 3.4. The contract helper does not write or
  mutate any file.
- Post-write JSON validation: Step 3.5. The contract helper does not
  load or parse any module artifact.

## 6. Test Coverage (33 new tests, total 110)

### `TestPatchContractValidation` (20 new tests, helper-level)

- `test_allowed_decision_types_match_design_and_prompt` -- pins the
  exact allowlist tuple against the design/prompt contract.
- `test_decision_type_constants_match_design` -- pins each per-decision
  constant value.
- `test_invalid_patch_contract_runner_status_is_stable` -- pins the new
  runner status name.
- `test_diagnostic_codes_for_step_3_1_are_stable` -- pins the 6 new
  diagnostic code constants.
- `test_valid_ready_patch_with_all_allowed_decision_types_passes` -- a
  ready plan with one entry per allowed decision type passes.
- `test_valid_ready_patch_with_minimal_shape_passes` -- minimal valid
  decision (only `{"decision": "delete_bogus_atom"}`) passes; shape
  helper does not require `from`/`to`/`reason`.
- `test_non_dict_patch_plan_rejected` -- None, str, int, list, tuple
  all rejected with a single `invalid_patch_contract` diagnostic.
- `test_wrong_version_rejected` -- bad version surfaces with
  `unsupported_version` diagnostic that names both the bad and
  expected version.
- `test_unsupported_status_rejected` -- unknown string status rejected.
- `test_unsupported_status_includes_non_string` -- non-string status
  also rejected.
- `test_decisions_not_list_rejected` -- non-list `decisions` rejected.
- `test_decisions_none_rejected` -- `decisions = None` rejected.
- `test_file_patches_not_list_rejected` -- non-list `file_patches`
  rejected.
- `test_file_patches_none_rejected` -- `file_patches = None` rejected.
- `test_decision_entry_not_dict_rejected` -- non-dict decision entry
  rejected with `[index]` in the message.
- `test_decision_missing_decision_key_rejected` -- entry without
  `decision` key rejected.
- `test_decision_decision_value_not_string_rejected` -- non-string
  `decision` value rejected.
- `test_unsupported_decision_type_rejected` -- string not in allowlist
  rejected with `unsupported_decision_type` and the bad value in the
  message.
- `test_multiple_contract_violations_all_reported` -- 4 distinct
  violations surface in a single pass.
- `test_file_patches_path_contents_pass_in_step_3_1_step_3_2_will_reject`
  -- ready plan with `file_patches: [{"path": "../unsafe.json", ...}]`
  PASSES Step 3.1 (list shape only). Test name is explicit so
  Step 3.2 can update the assertion.
- `test_does_not_mutate_input_plan` -- helper purity.
- `test_diagnostics_carry_severity_error` -- all contract diagnostics
  in this step are errors (no warning-only path yet).

### `TestPatchContractWiringInParseAndRunner` (11 new tests, wiring)

- `test_parse_ready_with_contract_violation_returns_invalid_patch_contract` --
  ready plan with unsupported decision type surfaces as
  `RUNNER_STATUS_INVALID_PATCH_CONTRACT` from `_parse_runner_response`.
- `test_parse_ready_with_valid_contract_returns_success` -- valid ready
  plan still succeeds.
- `test_parse_refused_with_contract_violation_appends_diagnostics` --
  refused plan with bad decision shape still returns
  `RUNNER_STATUS_REFUSED_RECONCILIATION` AND appends the contract
  diagnostic.
- `test_parse_failed_with_contract_violation_appends_diagnostics` --
  same contract for `failed`.
- `test_parse_refused_with_valid_contract_only_has_refused_diagnostic`
  -- pins Step 2.4 single-diagnostic contract for clean refused plans;
  the new contract helper does not regress this.
- `test_parse_failed_with_valid_contract_only_has_failed_diagnostic`
  -- pins Step 2.4 single-diagnostic contract for clean failed plans.
- `test_runner_ready_with_contract_violation_returns_invalid_patch_contract`
  -- end-to-end: ready plan with `{"decision": "nope"}` surfaces as
  `RUNNER_STATUS_INVALID_PATCH_CONTRACT` from the runner.
- `test_runner_ready_with_valid_contract_returns_success` -- valid ready
  plan with all 6 decision types returns `RUNNER_STATUS_SUCCESS`.
- `test_runner_refused_with_contract_violation_carries_both_diagnostics`
  -- end-to-end: refused + bad decision shape -> both
  `refused_reconciliation` and `invalid_decisions` diagnostics.
- `test_runner_failed_with_contract_violation_carries_both_diagnostics`
  -- end-to-end: failed + bad file_patches shape -> both
  `failed_reconciliation` and `invalid_file_patches` diagnostics.
- `test_runner_wrong_version_via_mock_provider_fails_closed` -- end-to-end:
  wrong patch version via mock_provider_output surfaces as
  `RUNNER_STATUS_INVALID_PATCH_CONTRACT` with `unsupported_version`.

### Total test counts

```
TestFinalReconciliationConstants           7 tests   (no change)
TestPromptLoading                         2 tests   (no change)
TestBriefSerialization                    4 tests   (no change)
TestChatMessageConstruction               5 tests   (no change)
TestResponseExtractionHelpers             4 tests   (no change)
TestRunnerPlumbing                        7 tests   (no change)
TestMockProviderOutputPath               10 tests   (no change)
TestDiagnosticAndParseHelpers             24 tests  (no change)
TestRunnerFailClosedDiagnostics           9 tests   (no change)
TestPatchContractValidation              20 tests  (NEW)
TestPatchContractWiringInParseAndRunner  11 tests  (NEW)
                                          ----
Total                                    110 tests  (was 77, +33)
```

The test runner is the source of truth (`Ran 110 tests in 0.007s`).

## 7. Style Consistency

- SPDX license header + module docstring preserved on the runner and
  test files.
- New constants grouped logically: allowed decision types after the
  existing `DIAGNOSTIC_CODE_*` group; new diagnostic codes appended to
  the existing `DIAGNOSTIC_CODE_*` group; new runner status appended to
  the existing `RUNNER_STATUS_*` group.
- New helper (`validate_final_reconciliation_patch_contract`) placed
  under a new `# Patch contract validation (Step 3.1)` section divider
  after the Step 2.4 parse helpers, so the file layout remains
  clean: constants -> prompt assembly -> response extraction ->
  Step 2.4 diagnostics/parse -> Step 3.1 contract validation -> final
  editor runner.
- Diagnostic dict shape remains the same small ASCII-only
  `{"code", "message", "severity"}` shape so reports and logs can
  serialize it without bespoke encoders.
- Existing legacy `error` field format preserved on every other status
  (`brief_not_dict`, `invalid_json`, `missing_required_keys: ...`,
  `refused_reconciliation`, `failed_reconciliation`, `provider_failed`,
  `param_resolution_failed`).
- New `error` field format for `invalid_patch_contract`:
  `"invalid_patch_contract: <message1>; <message2>; ..."` -- the same
  semicolon-joined aggregate used for `missing_required_keys`.
- All test names are ASCII-only and stable.
- Test file continues to use the standard
  `sys.path.append(str(Path(__file__).resolve().parents[1]))` import
  bootstrap.

## 8. Verification Commands Run

```bash
# Compile
.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py
# Result: PASS (no output)

# Tests (final-editor suite)
.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v
# Result: Ran 110 tests in 0.007s, OK (110 PASS, 0 FAIL)

# Step 1.4 regression set
.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety
# Result: Ran 74 tests in 0.080s, OK (74 PASS, 0 FAIL)
# (3 expected ERROR log lines from test_file_operations_path_safety
# are the spec-correct early-reject outcome from the Step 1.3 fix.)

# ASCII compliance
python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py
# Result: ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0

# OpenSpec strict validation
openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict
# Result: Change 'toolkit-accurate-ingest-llm-builder-final-editor' is valid

# Main spec validation
openspec validate --specs
# Result: Totals: 364 passed, 0 failed (364 items)
```

## 9. Scope Confirmation

This step delivers Step 3.1 only:

- Added 6 decision-type constants + 1 allowed-types tuple.
- Added 1 new runner status `RUNNER_STATUS_INVALID_PATCH_CONTRACT`.
- Added 6 new diagnostic codes for the Step 3.1 shape contract.
- Added pure helper `validate_final_reconciliation_patch_contract(patch_plan) -> (is_valid, diagnostics)`.
- Wired the helper into `_parse_runner_response`:
  - `status: ready` -> `RUNNER_STATUS_SUCCESS` only when contract passes;
    otherwise `RUNNER_STATUS_INVALID_PATCH_CONTRACT`.
  - `status: refused` / `status: failed` -> unchanged primary status;
    contract diagnostics appended to the diagnostic list.
- Updated `_build_error_message_for_status` to map the new status to
  `"invalid_patch_contract: <messages>"`.
- Added 33 new tests across 2 new test classes covering helper-level
  shape rules and parse-helper/runner-level wiring.
- Updated existing imports and added new exports to the test file.
- Updated `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`
  to mark Step 3.1 complete and document verification commands.
- Added this evidence file.

Out of scope and not implemented (per task spec):

- No file target / path validation. Step 3.2 owns editable-surface /
  path-traversal / runtime-only target rejection. The
  `test_file_patches_path_contents_pass_in_step_3_1_step_3_2_will_reject`
  test pins that file_patches[].path is NOT inspected in Step 3.1.
- No source-fidelity claim validation. Step 3.3 owns the source-fidelity
  honesty guard. A `status: ready` plan with `source_fidelity_claim: "pass"`
  still passes the contract helper because Step 3.1 only checks shape.
- No patch application. Step 3.4 owns atomic patch writes.
- No post-write JSON validation. Step 3.5 owns post-write validation.
- No packet-builder or finisher integration. The contract helper is a
  pure function; it does not import or call any packet-builder or
  finisher module.
- No edits to `web/extensions/toolkit_homebrew_packet_builder.py`,
  `web/extensions/toolkit_module_finisher.py`, or any module artifact.
- No live network or model calls in tests. The new contract-violation
  runner tests use `mock_provider_output=...` to drive the runner
  without touching the network. The contract helper itself is a pure
  function with no I/O.
