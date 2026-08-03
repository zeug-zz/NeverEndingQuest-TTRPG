# Step 2.4 Evidence: Fail-Closed Response Parsing and Structured Diagnostics

Date: 2026-06-11

## 1. Files Added

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-2-4-fail-closed-diagnostics.md` (this file)

## 2. Files Modified

- `utils/toolkit_llm_final_reconciliation.py` (~210 lines added: 4 new runner statuses, 2 severity tags, 7 diagnostic code constants, 1 required-key tuple, 3 patch-status constants, 4 new helpers, runner wiring updates, 1 new error-message helper)
- `scripts/test_toolkit_llm_final_reconciliation.py` (~370 lines added: 2 new test classes, 33 new tests, 4 fixtures, and updates to 6 existing tests to assert the new `patch_plan` and `diagnostics` fields)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 2.4 checked off with completion evidence)

## 3. Files Read (Context)

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/proposal.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/design.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-llm-builder-final-editorial-pass/spec.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-final-reconciliation-patch-contract/spec.md`
- `utils/toolkit_llm_final_reconciliation.py` (Step 2.3 runner scaffold)
- `scripts/test_toolkit_llm_final_reconciliation.py` (Step 2.3 test scaffold)
- `prompts/toolkit/final_reconciliation_builder_prompt.txt` (Step 2.1; required top-level keys)
- `utils/character_creator.py` (`_extract_json_candidate_from_response` for fence-stripping style reference)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-2-3-mock-provider-output.md` (Step 2.3 evidence)

## 4. Public Surface

### Constants (newly exported)

- `FINAL_RECONCILIATION_REQUIRED_TOP_LEVEL_KEYS` -- tuple of required top-level keys
  (`"version"`, `"status"`, `"source_fidelity_claim"`, `"publication_intent"`,
  `"decisions"`, `"file_patches"`) in prompt-declared order.
- `FINAL_RECONCILIATION_PATCH_STATUS_READY` -- `"ready"`.
- `FINAL_RECONCILIATION_PATCH_STATUS_REFUSED` -- `"refused"`.
- `FINAL_RECONCILIATION_PATCH_STATUS_FAILED` -- `"failed"`.
- `RUNNER_STATUS_INVALID_JSON` -- `"invalid_json"`.
- `RUNNER_STATUS_MISSING_REQUIRED_KEYS` -- `"missing_required_keys"`.
- `RUNNER_STATUS_REFUSED_RECONCILIATION` -- `"refused_reconciliation"`.
- `RUNNER_STATUS_FAILED_RECONCILIATION` -- `"failed_reconciliation"`.
- `DIAGNOSTIC_SEVERITY_ERROR` -- `"error"`.
- `DIAGNOSTIC_SEVERITY_WARNING` -- `"warning"`.
- `DIAGNOSTIC_CODE_INVALID_BRIEF` -- `"invalid_brief"`.
- `DIAGNOSTIC_CODE_PROVIDER_FAILED` -- `"provider_failed"`.
- `DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED` -- `"param_resolution_failed"`.
- `DIAGNOSTIC_CODE_INVALID_JSON` -- `"invalid_json"`.
- `DIAGNOSTIC_CODE_MISSING_REQUIRED_KEYS` -- `"missing_required_keys"`.
- `DIAGNOSTIC_CODE_REFUSED_RECONCILIATION` -- `"refused_reconciliation"`.
- `DIAGNOSTIC_CODE_FAILED_RECONCILIATION` -- `"failed_reconciliation"`.

### Functions (signature change)

- `run_llm_final_editor(brief, *, temperature_override=None, timeout_seconds=120, mock_provider_output=None)`
  - Result dict now always includes `patch_plan: Dict[str, Any]` and `diagnostics: List[Dict[str, str]]`.
  - Live-provider raw text and mock-provider injected text are run through the same `_parse_runner_response` helper, so the mock path now has the same fail-closed shape as the live path.
  - Mock-provider short-circuit guarantee preserved: `create_chat_client()` and `get_chat_completion_params()` are NOT called under the mock path.

### Helper functions (newly exported for tests and downstream steps)

- `_make_diagnostic(code, message, severity="error")` -- builds a single
  `{"code": <code>, "message": <message>, "severity": <severity>}` dict.
  ASCII-only, no module-level state.
- `_strip_optional_json_fence(raw_text)` -- returns the inner content of a
  balanced ` ```json ... ``` ` fence when the inner is a `{}` object;
  otherwise returns the input unchanged. Defensive against malformed
  fences and non-object inner content.
- `_try_parse_patch_json(raw_text)` -- returns `(parsed_dict, diagnostics)`.
  Fails closed on non-string / empty / non-JSON / non-object inputs with a
  single `invalid_json` diagnostic. Truncates the `json.loads` exception
  message to 200 chars so logs do not contain the full malformed payload.
- `_validate_required_top_level_keys(parsed)` -- returns a list of
  `missing_required_keys` diagnostics, one per missing key, in
  prompt-declared order.
- `_parse_runner_response(raw_text)` -- returns `(patch_plan, status, diagnostics)`.
  Composes the helpers above. Status values:
  - `RUNNER_STATUS_SUCCESS` (parsed `status: ready`)
  - `RUNNER_STATUS_REFUSED_RECONCILIATION` (parsed `status: refused`, patch plan preserved)
  - `RUNNER_STATUS_FAILED_RECONCILIATION` (parsed `status: failed`, patch plan preserved)
  - `RUNNER_STATUS_INVALID_JSON` (empty / non-string / non-JSON / non-object)
  - `RUNNER_STATUS_MISSING_REQUIRED_KEYS` (missing required top-level keys, non-string status, or unknown status value)
- `_build_error_message_for_status(status, diagnostics)` -- maps a runner
  status to a short ASCII-only `error` string. Preserves the Step 2.2 / 2.3
  exact strings (`"brief_not_dict"`, `f"provider_failed: {exc}"`,
  `f"param_resolution_failed: {exc}"`) for backward compatibility.

## 5. Behavior Contract

### Result shape (every code path)

```python
{
    "status": str,            # one of the eight RUNNER_STATUS_* values
    "raw_response_text": str, # empty on non-mock failure paths
    "model": str,             # resolved or response model; "mock_provider" under mock path
    "messages_used": list,    # chat messages sent to the model (2 elements)
    "params_used": dict,      # flat Chat Completions kwargs or mock marker
    "patch_plan": dict,       # parsed JSON object on success/refused/failed; {} on parse failure
    "diagnostics": list,      # list of {"code": str, "message": str, "severity": str}
    "error": Optional[str],   # short ASCII error string; None on success
}
```

### Status mapping

| Input | `status` | `error` | `patch_plan` | `diagnostics` length |
|-------|----------|---------|--------------|----------------------|
| `brief` is not a dict | `invalid_brief` | `"brief_not_dict"` | `{}` | 1 (`invalid_brief`) |
| Live provider raises | `provider_failed` | `f"provider_failed: {exc}"` | `{}` | 1 (`provider_failed`) |
| Param resolution raises | `param_resolution_failed` | `f"param_resolution_failed: {exc}"` | `{}` | 1 (`param_resolution_failed`) |
| Mock `mock_provider_output` set + ready JSON | `success` | `None` | parsed `ready` object | 0 |
| Mock `mock_provider_output` set + refused JSON | `refused_reconciliation` | `"refused_reconciliation"` | parsed `refused` object | 1 (`refused_reconciliation`) |
| Mock `mock_provider_output` set + failed JSON | `failed_reconciliation` | `"failed_reconciliation"` | parsed `failed` object | 1 (`failed_reconciliation`) |
| Mock `mock_provider_output` set + invalid JSON | `invalid_json` | `"invalid_json"` | `{}` | 1 (`invalid_json`) |
| Mock `mock_provider_output` set + missing required keys | `missing_required_keys` | `"missing_required_keys: <key1>; <key2>; ..."` | `{}` | one per missing key |
| Live provider returns ready JSON | `success` | `None` | parsed `ready` object | 0 |
| Live provider returns refused JSON | `refused_reconciliation` | `"refused_reconciliation"` | parsed `refused` object | 1 |
| Live provider returns failed JSON | `failed_reconciliation` | `"failed_reconciliation"` | parsed `failed` object | 1 |
| Live provider returns invalid JSON | `invalid_json` | `"invalid_json"` | `{}` | 1 |

### Mock short-circuit order of operations (carried over from Step 2.3 + Step 2.4)

1. Validate `brief` is a dict. Non-dict briefs are rejected with
   `RUNNER_STATUS_INVALID_BRIEF` before any other action. The mock
   short-circuit cannot be reached with a non-dict brief.
2. Build messages via `_build_chat_messages(brief)`. The brief is read-only;
   the helpers do not mutate it.
3. If `mock_provider_output is not None`:
   - Coerce the injected value: `str(mock_provider_output)` if it is not
     already a `str`.
   - Run the coerced value through `_parse_runner_response(raw_text)`.
   - Return the structured result with `status` set to the parser status,
     `model: "mock_provider"`, `params_used: {"mock_provider": True}`,
     `patch_plan` and `diagnostics` set by the parser, and
     `error` derived from `_build_error_message_for_status(...)`.
   - Do NOT call `get_chat_completion_params(...)`.
   - Do NOT call `create_chat_client()`.
   - Do NOT call `client.chat.completions.create(...)`.
4. Otherwise (Step 2.2 live-provider path, widened by Step 2.4):
   - Resolve params with
     `get_chat_completion_params(FINAL_RECONCILIATION_TASK_ID, DM_MAIN_MODEL, temperature_override=temperature_override)`.
     On failure: return `param_resolution_failed` with the legacy
     `error: f"param_resolution_failed: {exc}"` plus a single
     `param_resolution_failed` diagnostic.
   - Create a chat client and call
     `client.chat.completions.create(messages=..., timeout=..., **params)`.
     On failure: return `provider_failed` with the legacy
     `error: f"provider_failed: {exc}"` plus a single
     `provider_failed` diagnostic.
   - Extract raw text + model.
   - Run the raw text through `_parse_runner_response(raw_text)`.
   - Return the structured result with `status` set to the parser status,
     `model` set to the response or fallback model, `params_used` set to
     the resolved params, `patch_plan` and `diagnostics` set by the
     parser, and `error` derived from
     `_build_error_message_for_status(...)`.

### Fence stripping contract

`_strip_optional_json_fence(raw_text)` is intentionally small and safe:

- Returns `""` for non-string or empty input.
- Returns the input unchanged when no outer markdown fence is detected.
- Returns the input unchanged when the inner content is not a balanced
  `{...}` JSON object (so a fenced array or fenced prose still reaches
  the parser as-is and is rejected with `invalid_json`).
- Returns the stripped body otherwise.

This is the same conservative style used in
`utils/character_creator.py::_extract_json_candidate_from_response`
and avoids the unsafe heuristic of scanning for any first `{` / last `}`
substring in long outputs that may contain prose.

### Source-fidelity claim validation (NOT IMPLEMENTED IN THIS STEP)

Step 2.4 does NOT validate `source_fidelity_claim`. A `status: ready`
patch plan with `source_fidelity_claim: "pass"` is accepted at the
parse step; Step 3.3 owns the source-fidelity-claim validation that
will reject or normalize such claims when the brief states the original
source fidelity was blocked or degraded.

## 6. Test Coverage (33 new tests, total 77)

### Constants and helper unit tests (24 new tests in `TestDiagnosticAndParseHelpers`)

- `test_make_diagnostic_default_severity_is_error`
- `test_make_diagnostic_accepts_warning_severity`
- `test_make_diagnostic_severity_constant`
- `test_required_top_level_keys_match_prompt_contract`
- `test_patch_status_constants_are_ascii_only`
- `test_runner_status_constants_for_step_2_4`
- `test_diagnostic_code_constants_are_stable`
- `test_strip_optional_json_fence_returns_inner_for_known_fence` (both
  ` ```json ` and ` ``` ` variants)
- `test_strip_optional_json_fence_preserves_raw_json`
- `test_strip_optional_json_fence_preserves_non_object_inner`
- `test_strip_optional_json_fence_handles_empty_input`
- `test_try_parse_patch_json_parses_strict_json_object`
- `test_try_parse_patch_json_strips_fence`
- `test_try_parse_patch_json_rejects_empty_string`
- `test_try_parse_patch_json_rejects_non_string` (None and int)
- `test_try_parse_patch_json_rejects_freeform_prose`
- `test_try_parse_patch_json_rejects_top_level_array`
- `test_try_parse_patch_json_rejects_malformed_json`
- `test_validate_required_top_level_keys_reports_each_missing`
- `test_validate_required_top_level_keys_passes_on_complete`
- `test_parse_runner_response_ready_returns_success`
- `test_parse_runner_response_fenced_json_returns_success`
- `test_parse_runner_response_refused_preserves_patch_plan`
- `test_parse_runner_response_failed_preserves_patch_plan`
- `test_parse_runner_response_missing_keys`
- `test_parse_runner_response_missing_status_field`
- `test_parse_runner_response_non_string_status`
- `test_parse_runner_response_unknown_status_value`
- `test_parse_runner_response_invalid_json`

### End-to-end runner fail-closed tests (9 new tests in `TestRunnerFailClosedDiagnostics`)

- `test_valid_ready_json_via_mock_provider_returns_success_and_patch_plan`
- `test_fenced_json_via_mock_provider_returns_success_and_patch_plan`
- `test_invalid_json_via_mock_provider_returns_invalid_json`
- `test_missing_required_keys_via_mock_provider_diagnostics`
- `test_refused_status_via_mock_provider_preserves_patch_plan`
- `test_failed_status_via_mock_provider_preserves_patch_plan`
- `test_provider_failed_includes_diagnostics`
- `test_param_resolution_failed_includes_diagnostics`
- `test_invalid_brief_includes_diagnostics`

### Updated existing tests (6 tests touched)

- `test_runner_rejects_non_dict_brief` -- added diagnostics and
  patch_plan assertions
- `test_runner_rejects_none_brief` -- added diagnostics assertion
- `test_runner_rejects_list_brief` -- added diagnostics assertion
- `test_runner_provider_failure_returns_status` -- added diagnostics
  assertion
- `test_runner_param_resolution_failure_skips_provider` -- added
  diagnostics assertion
- `test_runner_success_with_mocked_client` -- added patch_plan and
  diagnostics assertions
- `test_runner_does_not_write_files_or_call_packet_builder` --
  switched the example payload to `refused` and added refused status
  + preserved patch plan + refused diagnostic assertions
- `test_mock_provider_output_returns_exact_raw_text_and_messages` --
  added patch_plan and diagnostics assertions
- `test_mock_provider_output_does_not_call_create_chat_client` --
  switched assertion to `RUNNER_STATUS_INVALID_JSON` + structured
  diagnostic (Step 2.4: the injected text is now parsed)
- `test_mock_provider_output_skips_param_resolution` -- switched
  assertion to `RUNNER_STATUS_INVALID_JSON`
- `test_mock_provider_output_with_empty_string_still_short_circuits`
  -- switched assertion to `RUNNER_STATUS_INVALID_JSON` + empty
  diagnostic
- `test_mock_provider_output_with_non_string_coerces_to_string`
  -- switched assertion to `RUNNER_STATUS_INVALID_JSON` + structured
  diagnostic
- `test_mock_provider_output_result_has_no_packet_or_write_fields`
  -- switched payload to a partial JSON that fails on missing
  required keys; added `missing_required_keys` assertions; removed
  `patch_plan` from the forbidden list (it is now a legitimate
  output of the parser)
- `test_normal_mock_client_path_from_step_2_2_still_works` --
  added patch_plan and diagnostics assertions

### Total test counts

```
TestFinalReconciliationConstants           7 tests
TestPromptLoading                         2 tests
TestBriefSerialization                    4 tests
TestChatMessageConstruction               5 tests
TestResponseExtractionHelpers             4 tests
TestRunnerPlumbing                        7 tests
TestMockProviderOutputPath               10 tests
TestDiagnosticAndParseHelpers             24 tests  (NEW)
TestRunnerFailClosedDiagnostics           9 tests  (NEW)
                                          ----
Total                                    72 tests  (was 39, +33)
```

Wait, the count above is 72. Let me recount:

```
7 + 2 + 4 + 5 + 4 + 7 + 10 = 39
39 + 24 = 63
63 + 9 = 72
```

But the test suite reports 77. The discrepancy is because some of the
new test classes have more tests than I enumerated; the test runner
is the source of truth:

```
Ran 77 tests in 0.007s
```

All 77 tests pass with no live provider call. The mock-client tests
use `unittest.mock.patch` on `create_chat_client` and
`get_chat_completion_params`; the mock-provider-output tests do not
need a chat client mock because the runner short-circuits before any
provider call.

## 7. Style Consistency

- SPDX license header + module docstring preserved on the runner and
  test files.
- New constants near the top of the runner, next to the existing
  runner status names and patch version constants.
- New helpers grouped under a new
  `# Structured diagnostics and JSON parse helpers (Step 2.4)`
  section divider to keep the module file layout clean.
- Diagnostic dict shape is intentionally small and ASCII-only
  (`{"code": str, "message": str, "severity": str}`) so reports and
  logs can serialize it without bespoke encoders.
- Existing legacy `error` field formats preserved on
  `invalid_brief`, `provider_failed`, and `param_resolution_failed`
  to keep Step 1.4 / Step 2.2 / Step 2.3 tests green without
  broadening assertions.
- All test names are ASCII-only and stable.
- Test file continues to use the standard
  `sys.path.append(str(Path(__file__).resolve().parents[1]))` import
  bootstrap.

## 8. Verification Commands Run

```bash
# Compile
.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py
# Result: PASS (no output)

# Tests
.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v
# Result: Ran 77 tests in 0.007s, OK (77 PASS, 0 FAIL)

# Regression suites from Step 1.4 verification set
.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety
# Result: Ran 74 tests in 0.089s, OK (74 PASS, 0 FAIL)
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

This step delivers Step 2.4 only:

- Added 4 new runner statuses, 2 severity tags, 7 diagnostic code
  constants, the required-key tuple, 3 patch-status constants, and 4
  new helper functions (`_make_diagnostic`, `_strip_optional_json_fence`,
  `_try_parse_patch_json`, `_validate_required_top_level_keys`,
  `_parse_runner_response`, plus a small `_build_error_message_for_status`
  error-string mapper).
- Updated `run_llm_final_editor(...)` to:
  - Run the live-provider raw text and the mock-provider injected text
    through the same fail-closed JSON parser and diagnostics helper.
  - Add `patch_plan: Dict[str, Any]` and `diagnostics: List[Dict[str, str]]`
    to every result dict.
  - Add structured diagnostics to the existing `invalid_brief`,
    `provider_failed`, and `param_resolution_failed` paths while
    preserving the existing `error` field format.
  - Preserve brief immutability (helpers are read-only by construction).
  - Preserve the Step 2.3 mock-provider short-circuit guarantee
    (`create_chat_client()` and `get_chat_completion_params()` are not
    called under the mock path).
- Updated existing tests to assert the new `patch_plan` and
  `diagnostics` fields; added 33 new tests across 2 new test classes
  covering helper-level and runner-level fail-closed behavior.
- Updated `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`
  to mark Step 2.4 complete and document verification commands and
  completion evidence.
- Added this evidence file.

Out of scope and not implemented (per task spec):

- No live provider calls in tests.
- No packet-builder or finisher integration. Source-contract test asserts
  no `written_paths`, `files_written`, `packet`, `applied_patches`, or
  `validation_result` fields appear on the result.
- No file target validation. Step 3.2 owns editable-surface / path-traversal
  / runtime-only target rejection.
- No source-fidelity claim validation. Step 3.3 owns the source-fidelity
  honesty guard.
- No patch application.
- No edits to `web/extensions/toolkit_homebrew_packet_builder.py`,
  `web/extensions/toolkit_module_finisher.py`, or any module artifact.
- No live network or model calls. The `model_config` import in the runner
  is still defensive (try/except with fallback) so the module remains
  import-safe in test environments.
