# Step 2.3 Evidence: Injected Mock-Provider Output Path

Date: 2026-06-11

## 1. Files Added

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-2-3-mock-provider-output.md` (this file)

## 2. Files Modified

- `utils/toolkit_llm_final_reconciliation.py` (~50 lines added: 2 new exported constants, 1 new optional runner kwarg, mock short-circuit branch, updated docstring)
- `scripts/test_toolkit_llm_final_reconciliation.py` (~190 lines added: 12 new tests across 2 new/extended test classes)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 2.3 checked off with completion notes)

## 3. Files Read (Context)

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/proposal.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/design.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-llm-builder-final-editorial-pass/spec.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-final-reconciliation-patch-contract/spec.md`
- `utils/toolkit_llm_final_reconciliation.py` (Step 2.2 runner scaffold)
- `scripts/test_toolkit_llm_final_reconciliation.py` (Step 2.2 test scaffold)
- `utils/ai_client_factory.py` (`create_chat_client`, `get_chat_completion_params` reference)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-2-2-llm-runner.md` (Step 2.2 evidence)

## 4. Public Surface

### Constants (newly exported)

- `RUNNER_MOCK_MODEL` -- `"mock_provider"` (string marker emitted on the result `model` field when the mock path is used)
- `RUNNER_MOCK_PARAMS_MARKER` -- `{"mock_provider": True}` (small marker dict emitted on `params_used` under the mock path)

### Functions (signature change)

- `run_llm_final_editor(brief, *, temperature_override=None, timeout_seconds=120, mock_provider_output=None)`
  - New optional keyword-only argument `mock_provider_output: Optional[str] = None`.
  - When `mock_provider_output is None` (the default), the runner uses the Step 2.2 live-provider plumbing unchanged.
  - When `mock_provider_output` is provided (any non-`None` value), the runner short-circuits before the live provider and param-resolution calls.

### Helper functions

No new helpers. All Step 2.2 helpers (`_load_final_reconciliation_prompt`, `_serialize_brief`, `_build_chat_messages`, `_extract_response_text`, `_extract_response_model`) remain the same.

## 5. Behavior Contract

### Mock short-circuit order of operations

1. Validate `brief` is a dict. Non-dict briefs are rejected with `RUNNER_STATUS_INVALID_BRIEF` before any other action. The mock short-circuit cannot be reached with a non-dict brief.
2. Build messages via `_build_chat_messages(brief)`. The brief is read-only; the helpers do not mutate it.
3. If `mock_provider_output is not None`:
   - Coerce the injected value: `str(mock_provider_output)` if it is not already a `str`.
   - Return:
     ```python
     {
         "status": "success",
         "raw_response_text": <coerced injected value>,
         "model": "mock_provider",
         "messages_used": <built messages list>,
         "params_used": {"mock_provider": True},
         "error": None,
     }
     ```
   - Do NOT call `get_chat_completion_params(...)`.
   - Do NOT call `create_chat_client()`.
   - Do NOT call `client.chat.completions.create(...)`.
4. Otherwise (Step 2.2 live-provider path, unchanged):
   - Resolve params with `get_chat_completion_params(FINAL_RECONCILIATION_TASK_ID, DM_MAIN_MODEL, temperature_override=temperature_override)`.
   - Create a chat client and call `client.chat.completions.create(messages=..., timeout=timeout_seconds, **params)`.
   - Return the existing structured result with `status`, `raw_response_text`, `model`, `messages_used`, `params_used`, `error`.

### Status mapping (mock path)

| Input | Output status | `error` | `model` | `params_used` |
|-------|---------------|---------|---------|---------------|
| `brief` is not a dict | `invalid_brief` | `"brief_not_dict"` | `""` | `{}` |
| `brief` is a dict, `mock_provider_output` is `None` | (live path) | (live path) | (resolved or response model) | (real params dict) |
| `brief` is a dict, `mock_provider_output` is a `str` | `"success"` | `None` | `"mock_provider"` | `{"mock_provider": True}` |
| `brief` is a dict, `mock_provider_output` is a non-`str` (e.g. dict, int) | `"success"` | `None` | `"mock_provider"` | `{"mock_provider": True}` |
| `brief` is a dict, `mock_provider_output` is an empty string | `"success"` | `None` | `"mock_provider"` | `{"mock_provider": True}` |

## 6. Test Coverage (12 new tests + 2 marker pins)

### `TestFinalReconciliationConstants` (2 new tests, total 7 in class)

- `test_mock_model_marker_is_ascii_string` -- pins the marker as an ASCII string.
- `test_mock_params_marker_is_small_marker` -- pins the marker dict shape so downstream code can rely on it.

### `TestMockProviderOutputPath` (10 new tests)

- `test_mock_marker_constants_are_present` -- pins the exported constants.
- `test_mock_provider_output_returns_exact_raw_text_and_messages` -- verifies the success result shape, exact raw text passthrough, system+user message shape, brief content in user message, brief not mutated, mock marker on `model` and `params_used`, and that `params_used` does NOT contain a real `model` key.
- `test_mock_provider_output_does_not_call_create_chat_client` -- patches `create_chat_client` and asserts it is not called under the mock path.
- `test_mock_provider_output_skips_param_resolution` -- patches `get_chat_completion_params` and `create_chat_client` and asserts neither is called.
- `test_mock_provider_output_does_not_mutate_brief` -- verifies the brief dict is unchanged after the mock invocation.
- `test_mock_provider_output_with_empty_string_still_short_circuits` -- empty-string raw output is a valid mock value and still takes the short-circuit path.
- `test_mock_provider_output_with_non_string_coerces_to_string` -- `{"foo": 1}` is coerced to `"{'foo': 1}"` via `str(...)`. Pins the chosen simplest contract.
- `test_mock_provider_output_with_non_dict_brief_still_rejected` -- brief validation runs first; the mock short-circuit cannot bypass a non-dict brief.
- `test_mock_provider_output_result_has_no_packet_or_write_fields` -- source contract: result does not carry `written_paths`, `files_written`, `packet`, `patch_plan`, `applied_patches`, or `validation_result` keys.
- `test_normal_mock_client_path_from_step_2_2_still_works` -- regression: when `mock_provider_output is None`, the runner continues to use the existing mock-client plumbing (`create_chat_client` called exactly once, response model preserved, `params_used` is a real params dict not the mock marker).

### Total test counts

```
TestFinalReconciliationConstants           7 tests  (was 5, +2)
TestPromptLoading                         2 tests
TestBriefSerialization                    4 tests
TestChatMessageConstruction               5 tests
TestResponseExtractionHelpers             4 tests
TestRunnerPlumbing                        7 tests
TestMockProviderOutputPath               10 tests  (NEW)
                                         ----
Total                                    39 tests  (was 27, +12)
```

All 39 tests pass with no live provider call. The mock-client tests use `unittest.mock.patch` on `create_chat_client` and `get_chat_completion_params`; the mock-provider-output tests do not need a chat client mock because the runner short-circuits before any provider call.

## 7. Style Consistency

- SPDX license header + module docstring preserved on the runner and test files.
- New constants near the top of the runner, next to the existing runner status names.
- New `mock_provider_output` keyword argument is keyword-only (follows existing `temperature_override` / `timeout_seconds` pattern).
- The mock short-circuit is placed after brief validation and message construction, before the existing param resolution and provider call, so the existing live-provider path is preserved byte-for-byte.
- `str(...)` coercion for non-string inputs is the simplest contract from the task spec; it matches the "convert safely to string" option.
- All test names are ASCII-only and stable.
- Test file continues to use the standard `sys.path.append(...)` import bootstrap.

## 8. Verification Commands Run

```bash
# Compile
.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py
# Result: PASS (no output)

# Tests
.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v
# Result: Ran 39 tests in 0.006s, OK (39 PASS, 0 FAIL)

# Regression suites from Step 1.4 verification set
.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety
# Result: Ran 74 tests in 0.089s, OK (74 PASS, 0 FAIL)
# (3 expected ERROR log lines from test_file_operations_path_safety are the
#  spec-correct early-reject outcome from the Step 1.3 fix; no regressions.)

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

This step delivers Step 2.3 only:

- Added the `mock_provider_output` optional keyword argument to `run_llm_final_editor(...)`. Backward compatible: existing callers that omit it get the unchanged Step 2.2 live-provider plumbing.
- Added 2 stable constants (`RUNNER_MOCK_MODEL`, `RUNNER_MOCK_PARAMS_MARKER`) and 12 new provider-free tests covering the mock path contract plus a regression test for the Step 2.2 normal mock-client path.
- Updated `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` to mark Step 2.3 complete with completion evidence.
- Added this evidence file.

Out of scope and not implemented (per task spec):

- No live provider calls in tests.
- No packet-builder or finisher integration. Source-contract test asserts no `packet`, `written_paths`, `files_written`, `patch_plan`, `applied_patches`, or `validation_result` fields appear on the result.
- No JSON parsing, required-key validation, or refusal handling of the injected output. Step 2.3 treats the injected output as opaque raw text; Step 2.4 owns fail-closed validation.
- No patch application.
- No edits to `web/extensions/toolkit_homebrew_packet_builder.py`, `web/extensions/toolkit_module_finisher.py`, or any module artifact.
- No live network or model calls. The `model_config` import in the runner is still defensive (try/except with fallback) so the module remains import-safe in test environments.
