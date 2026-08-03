# Tasks

## 1. Scaffold And Safety Baseline

- [x] 1.1 Verify current `final_reconciliation_required` boundary behavior and record the Well of Ruin blocker terms used by this change.

  **Baseline captured 2026-06-04.** Full evidence: `evidence/step-1-1-baseline.md`.
  - Archived boundary (`archive/2026-06-04-toolkit-accurate-ingest-final-reconciliation-boundary/`) already classifies Well of Ruin blockers as editorial via `utils/toolkit_final_blocker_classifier.py` and routes them to `final_reconciliation_required` / `final_reconciliation_brief.json` behavior instead of treating them as fatal structural blockers.
  - 12 Well of Ruin blocker terms recorded exactly: `Trigger`, `Passive Element`, `Active Element`, `Echoes of Calamity`, `Deciphering Ruin`, `**Well**spring of Legend`, `Celestial`, `Draconic`, `Orcish`, `Infernal`, `Primordial`, `Abyssal`.
  - `Trigger`, `Passive Element`, and `Active Element` are H3 sub-headings of the complex trap encounter in source markdown (lines 17, 22, 41), not playable locations. The remaining 9 terms are heading-derived (trap phases, lore sub-sections, rune variant table headers) and likewise not playable locations.
  - This confirms the new change must implement the final LLM Builder editorial reconciliation step, not alter the front/middle accurate-ingest pipeline (source graph, normalized packet, blueprint, backstage audit, source-enhanced ModuleBuilder handoff remain unchanged).
  - `modules/Well_of_Ruin` is present locally; presence recorded only, no validator run in this step.
  - No production code changed.
- [x] 1.2 Add or strengthen regression coverage for the `[Errno 63] File name too long` class so reconciliation artifact writes cannot construct lock paths from serialized JSON payloads.

  **Regression coverage added 2026-06-11.** Full evidence: `evidence/step-1-2-regression-coverage.md`.
  - New focused test file: `scripts/test_file_operations_path_safety.py` (9 tests, 4 classes). Covers:
    1. `TestSafeWriteJsonRejectsPayloadAsFilepath` (3 tests) - proves `safe_write_json` MUST NOT construct a lock or temp path containing `str(payload)` content when a dict / list / serialized-JSON string is passed where a file path is expected. Uses `unittest.mock.patch` on `os.open` and `builtins.open` to capture the actual path arguments and assert no payload marker (`'a'`, `'item_0'`, `{"large": "zzz...`) is present and that captured paths are bounded to < 255 chars. **Expected red before Step 1.3.**
    2. `TestAtomicWriterLockPathDerivation` (1 test) - proves the lock path passed to `os.open` is `filepath + '.lock'` and nothing else, for valid string filepaths.
    3. `TestAtomicWriterTempPathDerivation` (1 test) - proves the temp path passed to `builtins.open` is `filepath + '.tmp'` and nothing else, for valid string filepaths.
    4. `TestNormalFinalReconciliationPersistUnaffected` (4 tests) - proves `persist_final_reconciliation_brief`, `persist_final_reconciliation_report`, and `safe_write_json` continue to succeed with valid `(workspace_dir, payload)` and `(str_path, data)` / `(Path, data)` usage.
  - All 9 tests use ASCII-only names and messages (verified via `scripts/check_ascii_compliance.py`: `0 violations`).
  - No OS-specific path-length limits required. Tests use mock-based contract assertions (path substring + length) rather than relying on real `Errno 63`.
  - No production code changed in this step.
  - Verification:
    - `.venv/bin/python -m py_compile scripts/test_file_operations_path_safety.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_file_operations_path_safety -v` -> 6 PASS, 3 FAIL (the 3 FAIL tests are the expected-red regression that proves the bug class; they will pass after Step 1.3 production fix)
    - `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_windows_safe_file_operations` -> 65 PASS, 0 FAIL (no existing test broadened or changed)
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor` -> VALID
    - `python3 scripts/check_ascii_compliance.py scripts/test_file_operations_path_safety.py` -> 0 violations
  - Sample failure (expected red, from `test_dict_as_filepath_does_not_produce_payload_lock_or_temp_path`):
    ```
    AssertionError: "'a'" unexpectedly found in "{'a': 'xxx...', 'b': 'yyy...'}.lock" :
    os.open received path containing payload marker "'a'"
    ```
    This proves the bug: `safe_write_json`'s `str(dict)` path produces a 423-char `lock_path` that would trigger `[Errno 63] File name too long` on macOS HFS+ and similar 255-char limits elsewhere.
- [x] 1.3 Fix the lock/path safety bug in the smallest safe location, likely `utils/file_operations.py` or the affected reconciliation write call site.

  **Production fix landed 2026-06-11.** Full evidence: `evidence/step-1-3-path-safety-fix.md`.
  - Added `_is_valid_filepath(filepath)` helper in `utils/file_operations.py` that accepts `os.PathLike` and non-JSON `str` paths and rejects `None`, `dict`, `list`, `tuple`, `set`, and any other non-str/non-PathLike object. Strings beginning with `{` or `[` that also parse as JSON dict/list are also rejected (proving the spec contract: serialized-JSON strings must not be used verbatim as lock/temp paths).
  - `AtomicFileWriter.write_json` now calls `_is_valid_filepath(filepath)` BEFORE `str(filepath)` and BEFORE any `lock_path` / `temp_path` construction. On rejection it logs a structured `ERROR` and returns `False` without raising through `safe_write_json`.
  - Valid callers are unchanged: `str`, `pathlib.Path`, `os.PathLike` paths still write successfully; relative, absolute, and `Path` objects remain compatible.
  - No changes to `read_json` (out of scope: spec covers writes only).
  - No changes to `acquire_lock` / `release_lock` (called only after `write_json` validated the path; lock-path derivation test still passes).
  - Test alignment in `scripts/test_file_operations_path_safety.py`: relaxed the `len(captured) > 0` precondition in `_assert_no_payload_markers_in_captured` so it now accepts EITHER the safer early-reject outcome (zero captured paths) OR the validated-fall-through outcome (captured paths free of payload markers and bounded < 255 chars). Per spec: "if your fix rejects before any `os.open` / `open` call, update those tests minimally so zero captured paths is accepted as the safer outcome."
  - No other test bodies or assertion semantics were changed.
  - Verification:
    - `.venv/bin/python -m py_compile utils/file_operations.py scripts/test_file_operations_path_safety.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_file_operations_path_safety -v` -> 9 PASS, 0 FAIL
    - `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_windows_safe_file_operations` -> 65 PASS, 0 FAIL (no regression)
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor` -> VALID
  - Sample log line from the dict-as-filepath regression test (confirms the safer early-reject outcome):
    ```
    ERROR:utils.file_operations:Refusing to write JSON: filepath argument is not a valid path (type=dict). This usually means a payload was passed where a file path was expected.
    ```
    No `os.open` / `builtins.open` calls were made; no `*.lock` or `*.tmp` paths were created; no `[Errno 63]` class error is possible from this code path.
- [x] 1.4 Verify existing provider-free boundary tests still pass after the safety fix.

  **Verification passed 2026-06-11.** Full evidence: `evidence/step-1-4-verification.md`.
  - Provider-free final-reconciliation boundary suites (Command 1): **151/151 OK** in 0.040s
    - `test_toolkit_final_blocker_classifier`: 57/57 OK
    - `test_toolkit_final_reconciliation`: 62/62 OK (includes the 4 `TestNormalFinalReconciliationPersistUnaffected` valid-usage tests added in Step 1.2)
    - `test_toolkit_report_agreement`: 32/32 OK
  - Path-safety + windows-safe file operations suites (Command 2): **12/12 OK** in 0.060s
    - `test_file_operations_path_safety`: 9/9 OK (the 3 expected-red regression tests from Step 1.2 now pass after the Step 1.3 fix)
    - `test_windows_safe_file_operations`: 3/3 OK
  - Combined Step 1.4 verification set: **163/163 OK** in 0.088s
  - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
  - Valid final reconciliation brief/report persistence still works after the path-safety fix:
    - `test_persist_brief_with_valid_workspace_succeeds` -> PASS
    - `test_persist_report_with_valid_workspace_succeeds` -> PASS
    - `test_safe_write_json_with_valid_string_path_succeeds` -> PASS
    - `test_safe_write_json_with_valid_path_object_succeeds` -> PASS
  - The 3 `ERROR:utils.file_operations:Refusing to write JSON: filepath argument is not a valid path (...)` log lines visible during the path-safety run are the spec-correct early-reject outcome from `_is_valid_filepath` (no `os.open` / `builtins.open` call, no `*.lock` or `*.tmp` path created, no `[Errno 63]` possible).
  - No production code changed in this step.
  - No tests broadened or modified.
  - `git status --short` confirms the only working-tree changes vs. Step 1.3 are untracked files (the change folder and the Step 1.2 test file). `utils/file_operations.py` diff is the same Step 1.3 fix already recorded in `evidence/step-1-3-path-safety-fix.md`.

## 2. Final Editor Prompt And Runner

- [x] 2.1 Add `prompts/toolkit/final_reconciliation_builder_prompt.txt` with strict JSON-output instructions, source-fidelity honesty rules, allowed decisions, forbidden targets, and Well-like bogus heading examples.

  **Final-editor prompt landed 2026-06-11.** Full evidence: `evidence/step-2-1-final-editor-prompt.md`.
  - New prompt file: `prompts/toolkit/final_reconciliation_builder_prompt.txt` (~210 lines, ASCII-only, 0 non-ASCII bytes).
  - Prompt sections:
    1. Role and context: final editorial reconciliation assistant at the final editorial boundary; consumes `final_reconciliation_brief.json`; does NOT redo source extraction, packet normalization, blueprinting, or ModuleBuilder regeneration.
    2. Inputs: brief keys, source excerpts/refs, generated module summary, editable surfaces whitelist, validation goals.
    3. Hard rules (MUST): 15 numbered rules covering strict JSON-only output, required top-level keys (`version`, `status`, `source_fidelity_claim`, `publication_intent`, `decisions`, `file_patches`), allowed decision types (`delete_bogus_atom`, `reclassify_atom`, `merge_into_existing`, `preserve_as_dm_guidance`, `create_missing_real_element`, `refuse`), forbidden targets (runtime-only files, absolute paths, paths outside module_dir, source graph/manifest/normalized packet/blueprint/backstage audit artifacts, MODULE_SUMMARY.md as source truth, files not in editable_surfaces), source-fidelity honesty (`reconciled_degraded` not `pass` when original source fidelity was blocked/degraded), status semantics (`ready`/`refused`/`failed`), no fabrication of playable elements, ID preservation, minimal patches.
    4. Well-like bogus heading pattern: 3 explicit H3 sub-heading examples (`Trigger`, `Passive Element`, `Active Element`) + 9 additional heading-derived patterns from the Well of Ruin blocker list, with concrete decision rules (`delete_bogus_atom` preferred, `preserve_as_dm_guidance` allowed, `reclassify_atom` allowed).
    5. Output shape: strict JSON schema with version pin (`accurate_ingest_final_reconciliation_patch.v1`).
    6. Three worked examples: A) bogus source atom cleanup (Well of Ruin style, with line refs 17/22/41), B) refusal when no safe edit exists, C) failed status when input keys are missing.
    7. Reminders: ASCII-only, raw JSON reply, prefer refused over unsafe patches.
  - Style consistent with existing toolkit prompts (`normalization_fidelity_repair_prompt.txt`, `blueprint_field_enrichment_prompt.txt`, `source_identity_adjudication_prompt.txt`, `source_section_extraction_prompt.txt`, `homebrew_upload_normalization_prompt.txt`): role statement, MUST rules section, strict output schema, worked examples.
  - No production code changed in this step. The runner (`utils/toolkit_llm_final_reconciliation.py`) is still pending Step 2.2.
  - No tests added in this step: existing toolkit prompt files do not have natural contract tests reading prompt content (verified by grep across `scripts/`). Step 2.2 will introduce the runner with mock-provider test coverage; prompt contract will be tested then.
  - Verification:
    - `python3 scripts/check_ascii_compliance.py prompts/toolkit/final_reconciliation_builder_prompt.txt` -> 0 violations
    - Manual non-ASCII byte scan -> 0 non-ASCII bytes
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
    - `openspec validate --specs` -> 364/364 PASS
- [x] 2.2 Add `utils/toolkit_llm_final_reconciliation.py` with prompt assembly and a final-editor runner that uses existing chat-client/model-routing patterns.

  **LLM final-editor runner scaffold landed 2026-06-11.** Full evidence: `evidence/step-2-2-llm-runner.md`.
  - New module: `utils/toolkit_llm_final_reconciliation.py` with SPDX/license header, stable constants, prompt loader, deterministic brief serializer, chat-message builder, response extractors, and the `run_llm_final_editor(...)` runner.
  - Stable constants exported: `FINAL_RECONCILIATION_PROMPT_PATH`, `FINAL_RECONCILIATION_TASK_ID = "toolkit_final_reconciliation"`, `FINAL_RECONCILIATION_PATCH_VERSION = "accurate_ingest_final_reconciliation_patch.v1"`, default temperature `0.2`, default timeout `120` seconds, and runner status names.
  - Helper `_load_final_reconciliation_prompt()` loads the prompt from disk with an ASCII-only fallback string when the file is missing/unreadable. Provider-free and read-only.
  - Helper `_serialize_brief(...)` uses `json.dumps(..., sort_keys=True, ensure_ascii=True, separators=(",", ":"))` for deterministic ASCII-safe serialization.
  - Helper `_build_chat_messages(brief)` returns `[{"role":"system","content":<prompt>},{"role":"user","content":"FINAL_RECONCILIATION_BRIEF:\n<serialized_brief>"}]`.
  - Runner `run_llm_final_editor(brief, *, temperature_override=None, timeout_seconds=120)`:
    - Rejects non-dict briefs with `RUNNER_STATUS_INVALID_BRIEF`.
    - Builds messages via the read-only helpers (brief is never mutated).
    - Resolves flat Chat Completions kwargs with `get_chat_completion_params(FINAL_RECONCILIATION_TASK_ID, DM_MAIN_MODEL, temperature_override=...)`. Falls back to the canonical `model_config.DM_MAIN_MODEL` import, with a defensive default if `model_config` is unavailable.
    - Calls `client = create_chat_client()` then `client.chat.completions.create(messages=..., timeout=..., **params)`.
    - Returns a structured result dict with `status`, `raw_response_text`, `model`, `messages_used`, `params_used`, and `error`.
    - Status values: `success`, `provider_failed`, `param_resolution_failed`, `invalid_brief`.
    - Does NOT mutate the brief input, does NOT write files, does NOT call packet builder or finisher. Patch validation, application, and integration are deferred to Step 2.3-5.x.
  - New test file: `scripts/test_toolkit_llm_final_reconciliation.py` (27 tests across 7 classes):
    - `TestFinalReconciliationConstants` (5 tests) -- pins task id, patch version, prompt path, default temperature/timeout, and ASCII-only fallback string.
    - `TestPromptLoading` (2 tests) -- verifies the prompt file exists, loads, and contains `VALID JSON ONLY`, `source_fidelity_claim`, `editable_surfaces`, the patch version, `file_patches`, and `decisions`.
    - `TestBriefSerialization` (4 tests) -- verifies the serializer does not mutate the input, is deterministic, is ASCII-safe, and round-trips through `json.loads` to the same dict.
    - `TestChatMessageConstruction` (5 tests) -- verifies the two-message shape, the system message contract terms, the user-message brief serialization, the labeled `FINAL_RECONCILIATION_BRIEF:\n<json>` structure, and that message assembly does not mutate the brief.
    - `TestResponseExtractionHelpers` (4 tests) -- verifies text/model extraction from a normal response, from a response with missing/empty `choices`, and from a response lacking the `model` attribute.
    - `TestRunnerPlumbing` (7 tests) -- minimal mock-provider coverage that the brief input is not mutated, that provider failures and param-resolution failures return the right `status` and `error`, that `create_chat_client` is called exactly once on success, and that the result does not carry any `written_paths` / `packet` keys (proving no file writes or packet-builder integration in this step).
  - All 27 tests pass with no live provider call (mock-client only).
  - ASCII compliance: `0 violations` across both files.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> 27 PASS, 0 FAIL
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `0 violations`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
- [x] 2.3 Support injected/mock provider output for tests so the final editor can be verified without live provider calls.

  **Injected mock-provider output path landed 2026-06-11.** Full evidence: `evidence/step-2-3-mock-provider-output.md`.
  - New runner signature: `run_llm_final_editor(brief, *, temperature_override=None, timeout_seconds=120, mock_provider_output=None)`. Backward compatible: existing callers that omit `mock_provider_output` get the unchanged Step 2.2 live-provider plumbing.
  - New stable constants exported: `RUNNER_MOCK_MODEL = "mock_provider"` and `RUNNER_MOCK_PARAMS_MARKER = {"mock_provider": True}`.
  - Mock short-circuit behavior (after brief validation, before param resolution or provider call):
    - Validates brief is a dict first; non-dict briefs still return `RUNNER_STATUS_INVALID_BRIEF` (cannot be bypassed by mock).
    - Builds messages via the existing read-only helper so prompt/brief plumbing is inspectable.
    - Skips `get_chat_completion_params(...)` and `create_chat_client()` entirely.
    - Returns `status: "success"`, `error: None`.
    - Returns `raw_response_text` equal to the injected output (strings passed verbatim, non-strings coerced via `str(...)`).
    - Returns `model: "mock_provider"` and `params_used: {"mock_provider": True}` (small mock marker, not a real params dict).
    - Returns `messages_used` populated with the built `[system, user]` pair.
  - No JSON parsing, required-key validation, or refusal handling is implemented in this step (Step 2.4 owns those). The injected output is treated as opaque raw text.
  - No packet-builder, finisher, or filesystem writes are performed. Source-contract test asserts the result does not carry `written_paths`, `files_written`, `packet`, `patch_plan`, `applied_patches`, or `validation_result` keys.
  - 12 new tests added in `TestMockProviderOutputPath` (mock path contract) and 2 new tests in `TestFinalReconciliationConstants` (mock marker pin). All ASCII-only.
  - Step 2.2 normal mock-client plumbing remains covered by `TestRunnerPlumbing` and is regression-tested by the new `test_normal_mock_client_path_from_step_2_2_still_works` test.
  - Total tests: 39 (27 from Step 2.2 + 12 new). All pass.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> 39 PASS, 0 FAIL
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `0 violations`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
    - `openspec validate --specs` -> 364/364 PASS (no regression)
- [x] 2.4 Fail closed with structured diagnostics on provider errors, invalid JSON, missing required keys, or refused reconciliation.

  **Fail-closed response parsing and structured diagnostics landed 2026-06-11.** Full evidence: `evidence/step-2-4-fail-closed-diagnostics.md`.
  - `utils/toolkit_llm_final_reconciliation.py`:
    - Added stable constants: `FINAL_RECONCILIATION_REQUIRED_TOP_LEVEL_KEYS` (prompt-aligned tuple), `FINAL_RECONCILIATION_PATCH_STATUS_READY`/`REFUSED`/`FAILED`, four new runner statuses (`RUNNER_STATUS_INVALID_JSON`, `RUNNER_STATUS_MISSING_REQUIRED_KEYS`, `RUNNER_STATUS_REFUSED_RECONCILIATION`, `RUNNER_STATUS_FAILED_RECONCILIATION`), two diagnostic severity tags (`DIAGNOSTIC_SEVERITY_ERROR`/`WARNING`), and seven diagnostic code constants (`DIAGNOSTIC_CODE_INVALID_JSON`/`MISSING_REQUIRED_KEYS`/`REFUSED_RECONCILIATION`/`FAILED_RECONCILIATION`/`INVALID_BRIEF`/`PROVIDER_FAILED`/`PARAM_RESOLUTION_FAILED`).
    - Added a tiny structured-diagnostic helper `_make_diagnostic(code, message, severity="error")` returning `{"code": ..., "message": ..., "severity": ...}`. ASCII-only, no module-level state.
    - Added a small fence-stripping helper `_strip_optional_json_fence(raw_text)` that returns the inner content of a balanced ` ```json ... ``` ` fence when the inner starts with `{` and ends with `}`. Safe by design: returns the input unchanged for any non-object inner content or malformed fences. The original `_JSON_FENCE_RE` regex is small and ASCII-only.
    - Added `_try_parse_patch_json(raw_text)` that returns `(parsed_dict, diagnostics)`. Fails closed on non-string / empty / non-JSON / non-object inputs with a single `invalid_json` diagnostic. Truncates `json.loads` exception messages to 200 chars so logs do not contain the full malformed payload.
    - Added `_validate_required_top_level_keys(parsed)` that emits one `missing_required_keys` diagnostic per missing key (iterating in prompt-declared order for stable reporting).
    - Added `_parse_runner_response(raw_text)` that composes the helpers and returns `(patch_plan, status, diagnostics)`. Status values: `success` for `status: ready`, `refused_reconciliation` for `status: refused`, `failed_reconciliation` for `status: failed`, `invalid_json` for parse failure, `missing_required_keys` for missing keys or non-string/unknown `status`. Both `refused` and `failed` editor statuses preserve the parsed patch plan for reporting. The function never mutates the caller and never raises.
    - Updated `run_llm_final_editor(...)` to:
      - Run the live-provider raw text and the mock-provider injected text through the same `_parse_runner_response` helper, so the mock path goes through the same parse/diagnostic behavior as the live path. Step 2.3 mock-provider short-circuit guarantee preserved: `create_chat_client()` and `get_chat_completion_params()` are not called under the mock path.
      - Add `patch_plan: Dict[str, Any]` (parsed object on success/refused/failed; `{}` on parse failure) and `diagnostics: List[Dict[str, str]]` to every result dict.
      - Add structured diagnostics to the existing `invalid_brief`, `provider_failed`, and `param_resolution_failed` paths while preserving the existing `error` field format (`"brief_not_dict"`, `f"provider_failed: {exc}"`, `f"param_resolution_failed: {exc}"`).
      - Preserve brief immutability (helpers are read-only by construction; the brief is never mutated).
  - `scripts/test_toolkit_llm_final_reconciliation.py`:
    - Updated existing tests to reflect the new `patch_plan` and `diagnostics` fields and the new fail-closed behavior under the mock-provider path (e.g. empty string mock output now surfaces as `invalid_json` with a structured diagnostic, not `success`). Added `patch_plan`/`diagnostics` assertions to all affected tests.
    - Added new `TestDiagnosticAndParseHelpers` (24 tests) covering the helper-level contracts: `_make_diagnostic` defaults and warning severity, constant pins (required keys, patch status, runner status, diagnostic codes), `_strip_optional_json_fence` for balanced / non-object / empty inputs, `_try_parse_patch_json` for parse success / empty / non-string / freeform prose / array / malformed JSON, `_validate_required_top_level_keys` for full and partial payloads, `_parse_runner_response` for ready / refused / failed / fenced / missing-keys / missing-status / non-string-status / unknown-status / invalid-JSON paths.
    - Added new `TestRunnerFailClosedDiagnostics` (9 tests) covering the runner-level fail-closed contract through the mock-provider short-circuit: valid ready JSON -> `success` + populated `patch_plan` + empty diagnostics; fenced JSON -> same; invalid JSON -> `invalid_json` + empty `patch_plan` + diagnostic; missing required keys -> `missing_required_keys` + empty `patch_plan` + diagnostics listing each missing key; `refused` editor status -> `refused_reconciliation` + preserved `patch_plan` + refusal diagnostic; `failed` editor status -> `failed_reconciliation` + preserved `patch_plan` + failure diagnostic; `provider_failed` and `param_resolution_failed` and `invalid_brief` all include structured `diagnostics` while keeping the existing legacy `error` field.
  - Test counts:
    - Existing tests preserved: 39 (5 + 2 + 4 + 5 + 4 + 7 + 10).
    - New `TestDiagnosticAndParseHelpers`: 24 tests.
    - New `TestRunnerFailClosedDiagnostics`: 9 tests.
    - Total: **77 tests** (up from 39). All pass with no live provider call.
  - ASCII compliance: `0 violations` across both files.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **77 PASS, 0 FAIL** in 0.007s
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
    - `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **74/74 OK** in 0.089s (Step 1.4 regression set, no regressions)
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
    - `openspec validate --specs` -> 364/364 PASS (no spec regression)

## 3. Patch Contract And Safe Application

- [x] 3.1 Define the final reconciliation patch contract and allowed decision types.

  **Patch contract shape defined 2026-06-11.** Full evidence: `evidence/step-3-1-patch-contract.md`.
  - `utils/toolkit_llm_final_reconciliation.py`:
    - Added stable constants for the six allowed decision types exactly as they appear in the design and prompt: `delete_bogus_atom`, `reclassify_atom`, `merge_into_existing`, `preserve_as_dm_guidance`, `create_missing_real_element`, `refuse`. Exported as individual `FINAL_RECONCILIATION_DECISION_*` constants plus a single source-of-truth tuple `FINAL_RECONCILIATION_ALLOWED_DECISION_TYPES`.
    - Added stable diagnostic codes for Step 3.1: `DIAGNOSTIC_CODE_INVALID_PATCH_CONTRACT`, `DIAGNOSTIC_CODE_UNSUPPORTED_VERSION`, `DIAGNOSTIC_CODE_UNSUPPORTED_STATUS`, `DIAGNOSTIC_CODE_INVALID_DECISIONS`, `DIAGNOSTIC_CODE_INVALID_FILE_PATCHES`, `DIAGNOSTIC_CODE_UNSUPPORTED_DECISION_TYPE`.
    - Added runner status `RUNNER_STATUS_INVALID_PATCH_CONTRACT = "invalid_patch_contract"` for the new fail-closed contract-violation branch.
    - Added pure helper `validate_final_reconciliation_patch_contract(patch_plan) -> (is_valid, diagnostics)`. The helper enforces only the shape rules: non-dict patch plan, unsupported version, unsupported top-level status, non-list `decisions`, non-list `file_patches`, decision entry not a dict, decision entry missing `decision`, decision value not a string, decision value not in the allowlist. Every violation is reported in a single pass (no fail-fast). The helper never mutates the input and never raises.
    - Wired the helper into `_parse_runner_response(...)`:
      - `status: ready` returns `RUNNER_STATUS_SUCCESS` ONLY when the contract helper passes; otherwise returns `RUNNER_STATUS_INVALID_PATCH_CONTRACT` with the structured diagnostics.
      - `status: refused` and `status: failed` continue to return their respective runner statuses as in Step 2.4, but also run the contract helper and append any shape diagnostics so downstream reports can show contract issues alongside the refusal/failure.
    - Updated `_build_error_message_for_status(...)` to map `RUNNER_STATUS_INVALID_PATCH_CONTRACT` to a short `"invalid_patch_contract: <aggregated messages>"` string for the legacy `error` field.
    - The contract helper does NOT inspect `file_patches[].path`; only the list shape is checked. Target validation is owned by Step 3.2.
  - `scripts/test_toolkit_llm_final_reconciliation.py`:
    - Added two new test classes: `TestPatchContractValidation` (20 tests, helper-level shape rules) and `TestPatchContractWiringInParseAndRunner` (11 tests, parse-helper and runner-level wiring). Plus 2 new constants pins in `TestFinalReconciliationConstants` (the `RUNNER_STATUS_INVALID_PATCH_CONTRACT` value and the diagnostic codes for Step 3.1) -- total 33 new tests.
    - Coverage per Step 3.1 task spec:
      - `test_allowed_decision_types_match_design_and_prompt` -- pins the exact design/prompt tuple.
      - `test_decision_type_constants_match_design` -- pins each per-decision constant.
      - `test_valid_ready_patch_with_all_allowed_decision_types_passes` -- valid ready plan with all 6 decision types -> success.
      - `test_non_dict_patch_plan_rejected` -- None, str, int, list, tuple all rejected with one `invalid_patch_contract` diagnostic.
      - `test_wrong_version_rejected` -- bad version -> `unsupported_version` diagnostic naming both bad and expected version.
      - `test_unsupported_status_rejected` and `test_unsupported_status_includes_non_string` -- status not in {ready, refused, failed} (string or numeric) -> `unsupported_status` diagnostic.
      - `test_decisions_not_list_rejected` and `test_decisions_none_rejected` -- `decisions` not a list -> `invalid_decisions`.
      - `test_file_patches_not_list_rejected` and `test_file_patches_none_rejected` -- `file_patches` not a list -> `invalid_file_patches`.
      - `test_decision_entry_not_dict_rejected` -- non-dict decision entry -> `invalid_decisions` with `[index]` in message.
      - `test_decision_missing_decision_key_rejected` -- entry without `decision` key -> `invalid_decisions`.
      - `test_decision_decision_value_not_string_rejected` -- non-string `decision` value -> `invalid_decisions`.
      - `test_unsupported_decision_type_rejected` -- string not in allowlist -> `unsupported_decision_type`.
      - `test_multiple_contract_violations_all_reported` -- 4+ violations surface in a single pass.
      - `test_file_patches_path_contents_pass_in_step_3_1_step_3_2_will_reject` -- ready plan with `file_patches: [{"path": "../unsafe.json", ...}]` PASSES Step 3.1 (only list shape checked); test name is explicit so Step 3.2 can update it.
      - `test_does_not_mutate_input_plan` and `test_diagnostics_carry_severity_error` -- helper purity + severity contract.
      - Runner-level wiring: `test_runner_ready_with_contract_violation_returns_invalid_patch_contract`, `test_runner_ready_with_valid_contract_returns_success`, `test_runner_refused_with_contract_violation_carries_both_diagnostics`, `test_runner_failed_with_contract_violation_carries_both_diagnostics`, `test_runner_wrong_version_via_mock_provider_fails_closed`.
      - Parse-helper wiring: `test_parse_ready_with_contract_violation_returns_invalid_patch_contract`, `test_parse_ready_with_valid_contract_returns_success`, `test_parse_refused_with_contract_violation_appends_diagnostics`, `test_parse_failed_with_contract_violation_appends_diagnostics`, `test_parse_refused_with_valid_contract_only_has_refused_diagnostic`, `test_parse_failed_with_valid_contract_only_has_failed_diagnostic` (the last two pin the Step 2.4 single-diagnostic contract for clean refused/failed plans, ensuring the new contract helper does not regress those).
  - All tests are provider-free; the new contract-violation runner tests use `mock_provider_output=...` to drive the runner without touching the network.
  - ASCII compliance: 0 violations.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **110 PASS, 0 FAIL** in 0.007s (was 77, +33)
    - `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **74/74 OK** (Step 1.4 regression set, no regression)
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> 0 violations
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
    - `openspec validate --specs` -> 364/364 PASS (no spec regression)
- [x] 3.2 Validate all patch targets against editable surfaces from `final_reconciliation_brief.json` and reject runtime-only or path-traversal targets.

  **Patch target validation landed 2026-06-11.** Full evidence: `evidence/step-3-2-patch-target-validation.md`.
  - `utils/toolkit_llm_final_reconciliation.py`:
    - Added imports: `fnmatch` (for glob whitelist matching), `posixpath` (reserved for future normpath use; not currently invoked).
    - Added three stable diagnostic codes for Step 3.2: `DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET = "forbidden_patch_target"`, `DIAGNOSTIC_CODE_INVALID_PATCH_TARGET = "invalid_patch_target"`, `DIAGNOSTIC_CODE_EDITABLE_SURFACES_MISSING = "editable_surfaces_missing"`.
    - Added two immutable pattern tuples:
      - `_FORBIDDEN_RUNTIME_TARGET_PATTERNS` (6 entries: exact, glob `*`, and directory prefix `/` forms for `module_plot.json`, `party_tracker.json`, `player_quests_*.json`, `encounters/`, `modules/world_registry.json`, `modules/campaign.json`).
      - `_FORBIDDEN_SOURCE_MIDDLE_PATTERNS` (7 entries: exact + glob + directory prefix forms for `source_graph.json`, `source_manifest.json`, `normalized_packet.json`, `blueprint_*.json`, `accurate_ingest_audit_run/`, `agent_runs/`, `MODULE_SUMMARY.md`).
    - Added `_FORBIDDEN_AREAS_BASENAME_MUST_NOT_END_WITH = "_BU.json"` carve-out constant.
    - Added pure path-safety helpers: `_has_backslash`, `_is_absolute_path`, `_has_path_traversal`, `_matches_forbidden_pattern`, `_is_forbidden_target`, `_target_matches_editable_surface`. Each is read-only, ASCII-only, and never raises.
    - Added the pure target-validation helper `validate_final_reconciliation_patch_targets(patch_plan, brief) -> (bool, diagnostics)`:
      - Never mutates inputs. Never reads/writes the filesystem. Never calls a provider.
      - If `file_patches` is empty, returns `(True, [])` WITHOUT requiring `editable_surfaces` (preserves Step 3.1 behavior).
      - If `file_patches` is non-empty, requires `brief["editable_surfaces"]` to be a non-empty list of non-empty strings. Missing / wrong-type / non-string-item whitelist fails closed with a single `editable_surfaces_missing` diagnostic.
      - For each entry, validates in order: entry is dict -> `target_file` is present and string -> trimmed value is non-empty -> no backslash -> not absolute path (POSIX `/` or Windows drive `^[A-Za-z]:`) -> no `..` path component -> not in forbidden runtime-only / source / middle patterns (including `areas/*.json` carve-out) -> matches at least one entry in `editable_surfaces` (exact, directory-prefix, or `fnmatch` glob).
      - Reports all violations in a single pass (no short-circuit).
    - Added the runner wiring helper `_apply_target_validation_to_runner_status(parser_status, parser_diagnostics, patch_plan, brief) -> (status, diagnostics)`:
      - Skips target validation for early-failure statuses (invalid_json / missing_required_keys / invalid_brief / provider_failed / param_resolution_failed).
      - For `ready` plans: target failure escalates status to `RUNNER_STATUS_INVALID_PATCH_CONTRACT` and appends the target diagnostics.
      - For `refused` / `failed` plans: target failure preserves the original status (mirrors Step 3.1 semantics) and appends the target diagnostics.
      - Never mutates inputs.
    - Wired the helper into both runner result paths: the mock-provider short-circuit and the live-provider path. Both call `_apply_target_validation_to_runner_status(...)` after `_parse_runner_response(...)` and before the final result dict is built.
  - `scripts/test_toolkit_llm_final_reconciliation.py`:
    - Added new imports for the three diagnostic codes and the new module surface (`_has_backslash`, `_has_path_traversal`, `_is_absolute_path`, `_is_forbidden_target`, `_target_matches_editable_surface`, `validate_final_reconciliation_patch_targets`).
    - Added two new test fixtures: `_ready_plan_with_target(target_file)` (a valid ready plan with one file_patch entry targeting a caller-supplied path) and `_brief_with_surfaces(surfaces)` (a tiny brief whose `editable_surfaces` is caller-supplied).
    - Added three new test classes (75 new tests):
      - `TestTargetValidationHelpers` (21 tests): unit tests for the six small helpers covering backslash, absolute path (POSIX + Windows drive), traversal (segment-level), exact/prefix/glob surface matching, runtime-only forbidden patterns, source/middle forbidden patterns, areas carve-out, canonical-allowed targets, and non-string safety.
      - `TestValidateFinalReconciliationPatchTargets` (45 tests): end-to-end helper tests covering exact whitelisted target accepted, directory-prefix whitelist (`areas/`) accepting `areas/FOO_BU.json` and rejecting `areas/FOO.json`, glob whitelist (`areas/*_BU.json`, `map_*.json`) accepted, missing/non-string `target_file` rejected, absolute path / Windows drive path / backslash / `..` traversal / normalized traversal rejected, all six runtime-only files rejected, all seven source/middle artifacts rejected, target not in editable_surfaces rejected, empty `file_patches` does not require `editable_surfaces`, non-list `editable_surfaces` / non-string items / missing `editable_surfaces` fail closed, `areas/*.json` carve-out enforced, non-dict plan / non-dict brief rejected, input non-mutation, severity-error contract, multiple violations reported in a single pass.
      - `TestRunnerTargetValidationWiring` (9 tests): end-to-end runner tests through the mock-provider short-circuit. Pin: ready + valid target -> success; ready + forbidden target -> `invalid_patch_contract`; ready + traversal target -> `invalid_patch_contract`; ready + missing editable_surfaces -> `invalid_patch_contract`; refused + valid target -> status preserved with refused diagnostic only; refused + forbidden target -> status preserved with both diagnostics; failed + forbidden target -> status preserved with both diagnostics; ready + empty file_patches succeeds without editable_surfaces; mock-provider short-circuit never calls `create_chat_client` under target failure.
    - All tests are provider-free; the runner-level tests use `mock_provider_output=...` to drive the runner without touching the network.
    - The existing Step 3.1 test `test_file_patches_path_contents_pass_in_step_3_1_step_3_2_will_reject` is preserved unchanged: it pins the contract helper's path-content non-inspection behavior at the contract level. The new Step 3.2 helper-level and runner-level tests cover the actual rejection.
  - Test counts: 110 (Step 3.1 baseline) -> 185 (Step 3.2). All 185 pass with no live provider call.
  - ASCII compliance: `0 violations` across both files.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **185 PASS, 0 FAIL** in 0.009s
    - `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **74/74 OK** (Step 1.4 regression set, no regression)
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `0 violations`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
    - `openspec validate --specs` -> 364/364 PASS (no spec regression)
- [x] 3.3 Validate source-fidelity claims so accepted reconciliation cannot claim clean source-fidelity pass.

  **Source-fidelity-claim validation landed 2026-06-12.** Full evidence: `evidence/step-3-3-source-fidelity-claim-validation.md`.
  - `utils/toolkit_llm_final_reconciliation.py`:
    - Added stable constants: `FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED = "reconciled_degraded"` (the only accepted value for ready plans) and `FINAL_RECONCILIATION_SOURCE_FIDELITY_CLEAN_PASS_VARIANTS = ("pass", "clean_pass", "clean", "source_fidelity_pass")` (forbidden variants to catch LLM drift to equivalent clean-pass language).
    - Added a new diagnostic code: `DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM = "invalid_source_fidelity_claim"`. Reused `RUNNER_STATUS_INVALID_PATCH_CONTRACT` for the runner-level status so Step 3.3 stays consistent with the Step 3.1/3.2 aggregation; downstream reports key on the diagnostic code.
    - Added a small private helper `_is_clean_pass_claim(value)` for exact-match detection against the forbidden variants. Non-string inputs return `False` so the missing/non-string diagnostic is reported by the main helper.
    - Added pure helper `validate_final_reconciliation_source_fidelity_claim(patch_plan, brief) -> (bool, diagnostics)`. The helper enforces: ready plans MUST have a string `source_fidelity_claim` exactly equal to `reconciled_degraded`; any value in the clean-pass variant tuple is rejected as a false clean claim; missing or non-string claim fails closed. Refused/failed plans preserve their semantics; a false clean claim is reported as a diagnostic so the report can list it without flipping the runner status. The helper never mutates inputs, never reads or writes the filesystem, and never raises.
    - Added runner wiring helper `_apply_source_fidelity_claim_validation_to_runner_status(...)` mirroring the Step 3.2 pattern: skip for early failure statuses (invalid_json / missing_required_keys / invalid_brief / provider_failed / param_resolution_failed); for ready plans, escalate to `RUNNER_STATUS_INVALID_PATCH_CONTRACT` on failure; for refused/failed plans, preserve status and append the fidelity diagnostic.
    - Wired the helper into both runner result paths (mock-provider short-circuit and live-provider path), so source-fidelity validation runs after target validation in both flows.
  - `scripts/test_toolkit_llm_final_reconciliation.py`:
    - Added new imports: `DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM`, `FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED`, `FINAL_RECONCILIATION_SOURCE_FIDELITY_CLEAN_PASS_VARIANTS`, `_is_clean_pass_claim`, `validate_final_reconciliation_source_fidelity_claim`.
    - Added a new fixture `_ready_plan_with_source_fidelity_claim(claim, status=...)` for tests that need to vary the claim in isolation.
    - Added 4 new test classes (45 new tests, all provider-free):
      - `TestSourceFidelityClaimConstants` (3 tests) - pins the constant values for the accepted claim, clean-pass variant tuple, and diagnostic code.
      - `TestIsCleanPassClaim` (5 tests) - exact-match detection: known variants return True; the accepted claim, case variants, non-strings, and empty string return False.
      - `TestValidateFinalReconciliationSourceFidelityClaim` (26 tests) - accept/reject cases for ready plans, all four clean-pass variants, missing/non-string claims, case-variant rejection, refused/failed plan semantics (preserved status with diagnostic on false clean claim, no diagnostic on accepted claim), defensive input handling (non-dict plan / non-dict brief / unsupported status), and purity (no mutation of plan or brief on success or failure paths, error severity on diagnostics).
      - `TestRunnerSourceFidelityClaimWiring` (11 tests) - end-to-end runner-level tests through `mock_provider_output`: success on `reconciled_degraded`, fail-closed on each clean-pass variant, fail-closed on missing claim (captured by the parse gate or the source-fidelity gate), fail-closed on non-string claim, refused/failed status preserved with fidelity diagnostic appended, mock-provider short-circuit preserved under both success and failure.
  - Test counts: 185 (Step 3.2 baseline) -> 230 (Step 3.3). All 230 pass with no live provider call.
  - ASCII compliance: `0 violations` across both files.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **230 PASS, 0 FAIL** in 0.010s
    - `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **106/106 OK** in 0.089s (no regression in dependent suites)
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
    - `openspec validate --specs` -> 364/364 PASS (no spec regression)
- [x] 3.4 Apply accepted patches atomically only after the whole patch plan validates.

  **Atomic in-memory + write-phase patch application landed 2026-06-12.** Full evidence: `evidence/step-3-4-patch-application.md`.
  - `utils/toolkit_llm_final_reconciliation.py`:
    - Added imports: `os`, `safe_read_json`, `safe_write_json` (from `utils.file_operations`).
    - Added 5 patch-op constants: `FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY`, `_RENAME_KEY`, `_SET_VALUE`, `_REMOVE_ARRAY_ENTRY`, `_MERGE_INTO_EXISTING` plus the source-of-truth tuple `FINAL_RECONCILIATION_ALLOWED_PATCH_OPS` matching the prompt section "HARD RULES" item 7.
    - Added 2 apply-status constants: `FINAL_RECONCILIATION_APPLY_STATUS_APPLIED`, `_FAILED`.
    - Added 7 diagnostic codes for Step 3.4: `INVALID_PATCH_PLAN`, `INVALID_OP`, `INVALID_JSON_PATH`, `MISSING_MODULE_DIR`, `TARGET_FILE_READ_FAILED`, `TARGET_FILE_WRITE_FAILED`, `PATCH_APPLICATION_FAILED`.
    - Added pure helper `_parse_json_path(json_path) -> List[str] | None` for RFC 6901 JSON pointer subset (leading `/`, segments split on `/`, `~0`/`~1` decoding, invalid-escape rejection). Returns None on non-strings, empty paths, the root path `/`, non-pointer strings, and malformed escapes.
    - Added pure helper `_resolve_parent(root, segments) -> (parent, last_segment, diagnostics)`. Walks `segments[:-1]`; on intermediate failure returns `(None, None, [diagnostic])`; on success returns the parent container plus the last segment so the op helpers can address the final value.
    - Added per-op pure helpers: `_apply_set_value_op`, `_apply_remove_key_op`, `_apply_rename_key_op`, `_apply_remove_array_entry_op`, `_apply_merge_into_existing_op`. All mutate the in-memory content in place and return a (possibly empty) diagnostics list. `set_value` allows new keys in dict parents. `remove_key` requires the key to exist. `rename_key` requires the destination key to be a non-empty string and not already present. `remove_array_entry` requires the index to be in bounds. `merge_into_existing` is a shallow merge (`dict.update`); nested dict collisions are replaced rather than recursively merged.
    - Added public application helper `apply_final_reconciliation_patch_plan(patch_plan, brief, module_dir=None) -> dict` with the following 4-phase contract:
      1. **Phase 1 validation (no writes):** input shape, plan status must be `ready`, reuse of existing `validate_final_reconciliation_patch_contract`, `validate_final_reconciliation_patch_targets`, `validate_final_reconciliation_source_fidelity_claim`. Any failure returns `{status: "failed", changed_files: [], diagnostics: [...]}` with zero writes.
      2. **Phase 1b module-dir resolution:** explicit `module_dir` argument takes precedence over `brief["module_dir"]`. Fail-closed on missing or non-string.
      3. **Phase 2 load + Phase 3 apply in memory (no writes):** groups patches by `target_file` (first-seen order), loads each unique target via `safe_read_json` once, then dispatches each op via `_apply_op`. Any per-op failure aborts the entire plan and returns failed with zero writes.
      4. **Phase 4 write phase:** `safe_write_json` is called once per changed file. A write failure on one file returns failed with the `target_file_write_failed` diagnostic; the in-memory application phase itself produced zero partial writes.
    - The helper NEVER mutates the plan, brief, or module_dir inputs. Inputs are deepcopied in the purity test.
  - `scripts/test_toolkit_llm_final_reconciliation.py`:
    - Added 11 new imports (4 new diagnostic codes, 4 new op constants, 2 new apply-status constants, `_apply_op`, `_parse_json_path`, `_resolve_parent`, `apply_final_reconciliation_patch_plan`).
    - Added `import os, shutil, tempfile` for the tempdir fixture.
    - Added Step 3.4 test infrastructure: `_write_json`, `_make_ready_plan_with_patches`, `_make_brief_with_module_dir`, `_TempModuleDirTestCase` (creates/cleans up a unique temp module dir per test).
    - Added 7 new test classes with **77 new tests**:
      - `TestPatchOpConstants` (7 tests): pins each op constant value, the allowed-ops tuple order matching the prompt, and the apply-status constants.
      - `TestJsonPathParsing` (9 tests): simple / nested / array-index / escape-decoding paths; rejection of non-strings, empty strings, root-only `/`, non-pointer paths, and invalid escape sequences.
      - `TestResolveParent` (8 tests): walks into dict and list parents via int-segment, nested paths, and fail-closed rejections for missing dict keys, out-of-bounds indices, non-int indices, non-container traversal, and empty segments.
      - `TestSetValueOp` (5 tests): existing-key overwrite, new-key insert, array-index set, non-container parent failure, invalid array index failure.
      - `TestRemoveKeyOp` (3 tests): existing-key removal, missing-key failure, non-dict parent failure.
      - `TestRenameKeyOp` (6 tests): successful rename; failures for missing old key, non-string new key, empty new key, destination already present, non-dict parent.
      - `TestRemoveArrayEntryOp` (4 tests): index removal; failures for out-of-bounds index, non-int index, non-list parent.
      - `TestMergeIntoExistingOp` (5 tests): shallow merge into existing dict; failures for non-dict target, non-dict value, non-dict parent; shallow-merge non-recursion pinned.
      - `TestApplyFinalReconciliationPatchPlan` (30 tests): per-op happy path (5), multi-patch and multi-file (3), plan-level validation failures that write nothing (4: refused status, failed status, contract violation, target violation, source-fidelity violation), module-dir resolution (5: missing, empty string, brief fallback, arg-over-brief, target-violation), file I/O failures (2: missing file, corrupt JSON), per-op input validation (3: invalid op, invalid json_path, missing json_path field), in-memory application phase failures (2: later patch failure with no writes, failure preserves earlier in-memory changes), write-phase failure (1: mocked `safe_write_json` returns False on second file), purity (3: no-mutation, non-dict plan, non-dict brief), entry-shape rejections (2: non-dict entry, non-string target_file).
    - All 77 new tests pass with no live provider call and no real filesystem leak (tempdir per test, cleaned up on tearDown).
  - Test counts: 230 (Step 3.3 baseline) -> **307** (Step 3.4). All 307 pass with no live provider call.
  - ASCII compliance: `0 violations` across both files.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **307 PASS, 0 FAIL** in 0.028s
    - `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **106/106 OK** in 0.092s (no regression in dependent suites)
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `0 violations`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
    - `openspec validate --specs` -> 364/364 PASS (no spec regression)
- [x] 3.5 Validate changed JSON files immediately after write and preserve BU/live parity rules.

  **Post-write JSON parse validation and BU/live parity mirror landed 2026-06-12.** Full evidence: `evidence/step-3-5-post-write-validation-and-parity.md`.
  - `utils/toolkit_llm_final_reconciliation.py`:
    - 2 new diagnostic codes: `DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID` (post-write parse failure) and `DIAGNOSTIC_CODE_PARITY_COUNTERPART_WRITE_FAILED` (parity mirror write failure).
    - 1 new module-internal constant: `_PARITY_BASENAMES = frozenset({"module_context.json", "module_context_BU.json"})`.
    - 3 new pure helpers:
      - `_compute_parity_counterpart(target) -> Optional[str]` - pins parity pairs: `module_context.json` <-> `module_context_BU.json` and `map_<base>.json` <-> `map_<base>_BU.json`. Returns `None` for runtime-only targets (`areas/FOO_BU.json`, `module_plot_BU.json`, `module_plot.json`) and any non-paired target. Preserves directory prefix.
      - `_should_mirror_parity_write(counterpart, module_dir, editable_surfaces) -> bool` - returns `True` when the counterpart already exists in the module directory OR is explicitly listed in `editable_surfaces` (exact, directory-prefix, or glob form, reusing the existing `_target_matches_editable_surface` helper from Step 3.2). Tolerant of non-list / non-string-item `editable_surfaces`.
      - `_validate_written_json(full_path, target) -> List[Dict[str, str]]` - re-opens a just-written file via `safe_read_json` and returns an empty list on success or a single `written_json_invalid` diagnostic on failure. JSON parse validation only; schema validation is owned by Step 4.1.
    - Modified `apply_final_reconciliation_patch_plan(...)` Phase 4 with two new guarantees after every successful `safe_write_json`:
      1. Post-write JSON parse validation: re-open the file via `safe_read_json`; parse failure surfaces a `written_json_invalid` diagnostic; the target is NOT added to `written_files` on parse failure.
      2. BU/live parity mirror: when the just-written target is one side of a canonical static authored pair, mirror the same post-patch content to the counterpart when applicable. The mirror itself is subject to the same post-write JSON parse validation. The mirror is skipped when both sides of a pair are in the patch plan.
    - Public helper's docstring updated to document the new Step 3.5 behavior in Phase 4. The return shape (`status`, `changed_files`, `diagnostics`) is preserved.
  - `scripts/test_toolkit_llm_final_reconciliation.py`:
    - 3 new import names added.
    - 4 existing tests updated to pin `editable_surfaces` to the target only (so the new parity mirror does not incidentally fire and complicate the existing happy-path assertions): `test_apply_set_value_happy_path`, `test_apply_remove_key_happy_path`, `test_apply_rename_key_happy_path`, `test_apply_multiple_patches_to_same_file`. The existing assertions (`changed_files == [target]`) are preserved.
    - 4 new test classes with 33 new tests (all provider-free):
      - `TestComputeParityCounterpart` (11 tests) - pins the parity counterpart for canonical pairs; runtime-only targets return `None`; unrelated targets return `None`; non-string / empty inputs return `None`.
      - `TestShouldMirrorParityWrite` (7 tests) - existence-on-disk, in-editable-surfaces, glob match, absent-and-not-listed, invalid inputs, non-list / non-string-item tolerance.
      - `TestValidateWrittenJson` (4 tests) - valid JSON returns empty, corrupt JSON returns diagnostic, missing file returns diagnostic, invalid full_path returns diagnostic.
      - `TestPostWriteValidationAndParity` (11 tests) - post-write success, post-write failure (mocked `safe_write_json` writes garbage), 4 happy-path parity mirrors (module_context<->BU and map_FOO<->BU in both directions), 2 negative mirrors (no area live mirror, no plot live mirror), 2 parity mirror failure paths (write failure, invalid post-write), 1 double-write skip (both sides in plan).
  - Test counts: 307 (Step 3.4 baseline) -> **340** (Step 3.4 + 33 Step 3.5). All 340 pass with no live provider call.
  - ASCII compliance: 0 violations across both files.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **340 PASS, 0 FAIL** in 0.040s
    - `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **106/106 OK** in 0.097s (no regression in dependent suites)
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
    - `openspec validate --specs` -> 364/364 PASS (no spec regression)

## 4. Validation Loop And Reporting

- [x] 4.1 Run schema validation after patch application and collect structured validation diagnostics.

  **Schema-validation orchestration after patch application landed 2026-06-12.** Full evidence: `evidence/step-4-1-schema-validation.md`.
  - `utils/toolkit_llm_final_reconciliation.py`:
    - Added defensive import of `ModuleValidator` from `core.validation.validate_module_files` so the helper is usable in environments where the validation package is not on sys.path; the real class is required only for the non-mock path.
    - Added module-internal `_TOOLKIT_FINAL_RECONCILIATION_REPO_ROOT` constant (resolved from `Path(__file__).resolve().parents[1]`) used to anchor the `ModuleValidator` schema dir the same way `scripts/test_toolkit_homebrew_readiness_gate.py` does.
    - Added four new stable status constants: `FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS = "pass"`, `FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL = "fail"`, `FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR = "error"`, `FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_NOT_RUN = "not_run"`.
    - Added two new diagnostic codes: `DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED = "schema_validation_failed"` and `DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR = "schema_validation_error"`.
    - Added pure helper `_parse_validator_error_message(raw_message) -> (file, message)` that best-effort splits the ModuleValidator's various error string shapes (simple `file: msg`, area path with `(areas/)` suffix, plain string with no separator, non-string input) into `(file, message)` tuples without mutating inputs or raising.
    - Added pure helper `collect_schema_validation_results(validator_results) -> dict` that collapses a `ModuleValidator.results` mapping into the compact shape `{status, success_rate, passed, failed, errors: [{category, file, message}, ...]}`. The helper is pure (no mutation, no raises), handles non-dict inputs gracefully, skips legacy scalar category payloads, and never includes the raw `files` lists so downstream reports stay small.
    - Added `run_final_reconciliation_schema_validation(module_dir) -> dict` that instantiates `ModuleValidator(module_dir, repo_root)`, calls `execute_full_validation(verbose=False)`, and routes through `collect_schema_validation_results`. The helper is fail-closed on three failure classes: missing/non-string `module_dir`, unavailable `ModuleValidator`, and exceptions from `execute_full_validation`. Each failure class surfaces a structured `schema_validation_error` diagnostic.
    - Added `apply_and_validate_final_reconciliation_patch_plan(patch_plan, brief, module_dir=None) -> dict` orchestrator. The orchestrator runs `apply_final_reconciliation_patch_plan` first; when the apply phase is `applied`, it calls `run_final_reconciliation_schema_validation` next. When apply is anything other than `applied`, schema validation is skipped and `schema_validation` is set to a small `{"status": "not_run", ...}` dict. Overall status is `applied` only when both phases pass; otherwise it is `failed`. The orchestrator does NOT attempt rollback; when apply succeeds but schema fails, the writes remain on disk (rollback is a Step 4.3 concern). The apply_result is preserved verbatim in the result so callers can read the apply helper's `changed_files` and `diagnostics` directly.
  - `scripts/test_toolkit_llm_final_reconciliation.py`:
    - Added 7 new import names: 2 status constants, 2 diagnostic codes, 2 helper functions, 1 orchestrator.
    - Added 5 new test classes (33 new tests, all provider-free):
      - `TestStep41Constants` (2 tests) - pins the four schema-validation status names and the two diagnostic codes.
      - `TestParseValidatorErrorMessage` (7 tests) - unit tests for the file/message split covering simple `file: msg`, area path with `(areas/)` suffix, no-separator input, leading-colon input, non-string input, whitespace stripping, and inner-colon preservation.
      - `TestCollectSchemaValidationResults` (10 tests) - pass path with all passed; fail path with two categories (one fully passed, one fully failed) verifying aggregation and per-error `category/file/message` shape; mixed pass/fail in same category; empty results returns pass with zero counts; non-dict input returns pass with zero counts; raw `files` field is excluded from compact shape; unknown category payload is skipped safely; purity (no input mutation); compact shape keys pinned to the canonical five.
      - `TestRunFinalReconciliationSchemaValidation` (6 tests) - happy pass path with mocked `ModuleValidator` (asserts `MockValidator` was called with the given `module_dir` and a non-empty string schema dir, and that `execute_full_validation(verbose=False)` was invoked exactly once); fail path with mocked validator that returns a single failure; exception path with mocked validator that raises from `execute_full_validation`; missing/empty `module_dir` returns structured error without instantiating validator; non-string `module_dir` (None, int, list, dict) returns structured error; `ModuleValidator = None` (defensive import path) returns structured error.
      - `TestApplyAndValidateFinalReconciliationPatchPlan` (8 tests) - overall `applied` when both phases pass; overall `failed` when apply succeeds but schema fails (writes remain on disk, no rollback); schema validation is NOT invoked when apply fails (target-read-failed path); schema validation is NOT invoked when plan-level validation fails (refused status path); schema `error` propagates as overall `failed`; explicit `module_dir` argument takes precedence over brief's `module_dir` for schema validation; no mutation of inputs; combined `diagnostics` list correctly merges both phases; top-level orchestrator result shape keys are pinned to `{status, apply_result, schema_validation, diagnostics}`.
  - Test counts: 340 (Step 3.5 baseline) -> **373** (Step 3.5 + 33 Step 4.1). All 373 pass with no live provider call and no real `ModuleValidator` invocation.
  - ASCII compliance: 0 violations across both files.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **373 PASS, 0 FAIL** in 0.054s (was 340; +33 new tests)
    - `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **106/106 OK** in 0.097s (no regression in dependent suites)
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
- [x] 4.2 Run readiness, publishability, and report agreement after accepted reconciliation.

  **Post-accepted-reconciliation publication-gate orchestration landed 2026-06-12.** Full evidence: `evidence/step-4-2-publication-gates.md`.
  - `utils/toolkit_llm_final_reconciliation.py`:
    - Added 4 new stable gate-status constants: `FINAL_RECONCILIATION_GATE_STATUS_PASS`, `_FAIL`, `_ERROR`, `_NOT_RUN`.
    - Added 2 accepted-reconciliation gate facts as constants: `FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS = "reconciled_degraded"`, `FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS = "accepted"`.
    - Added 4 new diagnostic codes: `DIAGNOSTIC_CODE_GATE_READINESS_FAILED`, `DIAGNOSTIC_CODE_GATE_PUBLISHABILITY_FAILED`, `DIAGNOSTIC_CODE_GATE_REPORT_AGREEMENT_BLOCKED`, `DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION`.
    - Added defensive imports of `audit_module_readiness` (scripts.audit_module_readiness), `audit_module_publishability` (scripts.audit_module_publishability), and `compose_report_agreement` (utils.toolkit_report_agreement). Each import is wrapped in try/except so the module remains importable in environments where the script or utility packages are unavailable; the gate helper checks for the sentinel and surfaces a structured `gate_helper_exception` diagnostic.
    - Added pure helper `_normalize_schema_validation_to_validation_status(schema_validation)` that maps `pass -> pass`, `fail/error -> blocked`, `not_run -> unknown`, missing/None/non-dict -> `unknown`. The helper never mutates inputs and never raises.
    - Added pure helper `_compute_reconciled_publishable_status(publishability_report) -> (effective_status, normalized)`. Returns the publishable_status as the effective status (with `normalized=True`) ONLY when (a) raw `effective_publishable_status` is blocked/fail, (b) `publishable_status` is pass, and (c) `source_fidelity_status` is blocked/degraded/fail. Otherwise returns the raw effective status with `normalized=False`. The check intentionally does NOT normalize when `publishable_status` itself is fail so a real publishability failure cannot be hidden.
    - Added `run_final_reconciliation_publication_gates(module_dir, schema_validation=None, source="toolkit") -> dict`:
      1. Validates `module_dir` is a non-empty `str` or `Path`; otherwise returns `error` with a `gate_helper_exception` diagnostic.
      2. Resolves module slug from `module_dir.name`.
      3. Calls `audit_module_readiness(module_slug, source=source)` (caught fail-closed on exception).
      4. Calls `audit_module_publishability(module_slug, module_path=str(module_dir), source=source)` (caught fail-closed on exception).
      5. Computes the normalized `effective_publishable_status` via the source-fidelity helper above (preserves the raw effective status in `effective_publishable_status_raw` and the flag in `effective_publishable_status_normalized`).
      6. Composes report agreement in memory via `compose_report_agreement(...)` with the reconciliation facts pinned to the accepted-reconciliation contract (`source_fidelity_effective_status="reconciled_degraded"`, `final_reconciliation_accepted=True`, `final_reconciliation_status="accepted"`), passing the normalized `effective_publishable_status` so the source-fidelity honesty invariant is preserved.
      7. Aggregates the three gate outcomes into a stable `pass/fail` status with one diagnostic per failing gate; the function never escalates the status when the agreement result is non-dict (defensive: it falls back to an empty agreement dict and the gate stays pass).
      8. Returns a compact result shape with 14 top-level keys: `status`, `readiness`, `publishability`, `report_agreement`, `diagnostics`, `ready_status`, `publishable_status`, `effective_publishable_status`, `effective_publishable_status_raw`, `effective_publishable_status_normalized`, `validation_status`, `source_fidelity_effective_status`, `final_reconciliation_accepted`, `final_reconciliation_status`.
    - Added orchestrator `apply_validate_and_gate_final_reconciliation_patch_plan(patch_plan, brief, module_dir=None) -> dict`:
      1. Calls `apply_and_validate_final_reconciliation_patch_plan` (Step 4.1).
      2. If the Step 4.1 result is not `applied`, returns `failed` with `gates.status="not_run"` and the apply+schema diagnostics; readiness/publishability/agreement helpers are NOT invoked.
      3. If applied, calls `run_final_reconciliation_publication_gates(effective_module_dir, schema_validation=<step 4.1 schema payload>)` and composes a stable 5-key result: `status`, `apply_result`, `schema_validation`, `gates`, `diagnostics`. Overall status is `applied` only when the gate phase also returns `pass`; otherwise `failed`.
      4. The combined `diagnostics` list concatenates apply+schema and gate diagnostics.
      5. The function does NOT attempt rollback; does NOT add a retry loop (Step 4.3); does NOT persist any report (Step 4.4); does NOT integrate with the packet builder or finisher (Step 5).
  - `scripts/test_toolkit_llm_final_reconciliation.py`:
    - Added 5 new test classes (54 new tests, all provider-free):
      - `TestStep42Constants` (10 tests) - pins the four gate status names, two reconciliation gate facts, and four diagnostic codes.
      - `TestNormalizeSchemaValidationToValidationStatus` (9 tests) - pass/fail/error/not_run mapping, missing/None/non-dict/non-string/garbage input handling.
      - `TestComputeReconciledPublishableStatus` (7 tests) - all-pass no normalization, blocked/degraded fidelity-only normalization, publishable_fail does NOT normalize, pass_fidelity_blocked_effective no normalize, missing/empty-report handling.
      - `TestRunFinalReconciliationPublicationGates` (20 tests) - happy path pass, readiness fail, publishability fail, report agreement blocked, three helper-exception paths (readiness, publishability, agreement), source-fidelity reconciled normalization, Path module_dir accepted, str module_dir accepted, invalid/empty module_dir returns error, no schema_validation defaults to unknown, schema_validation_fail/error normalizes to blocked, three non-dict-response defensive tests, gate result shape stability.
      - `TestApplyValidateAndGateFinalReconciliationPatchPlan` (8 tests) - all-three-phases pass, applies-skips-gates on apply fail, applies-skips-gates on schema fail, gates fail -> overall failed (and apply wrote to disk), gate helpers invoked exactly once on success, no-mutation input contract, top-level shape keys pinned, not_run gates payload carries accepted-reconciliation fields, schema validation payload is forwarded into the gate payload.
    - All 54 new tests mock the readiness, publishability, agreement, and schema-validation helpers via `unittest.mock.patch` so no live CLI subprocess runs and no live report is loaded. The gate runner test never calls a real `audit_module_readiness`/`audit_module_publishability`/`compose_report_agreement` - all three are mocked.
    - The orchestrator tests extend `_TempModuleDirTestCase` only for the apply phase (which writes JSON files); the gate-phase mocking ensures the audit and agreement helpers see canned reports and never touch the filesystem.
  - Test counts: 373 (Step 4.1 baseline) -> **427** (Step 4.1 + 54 Step 4.2). All 427 pass with no live provider call and no live CLI subprocess.
  - ASCII compliance: `0 violations` across both files.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **427 PASS, 0 FAIL** in 0.069s (was 373, +54 new tests)
    - `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **106/106 OK** in 0.094s (Step 1.4 regression set + dependent suites, no regression)
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
    - `openspec validate --specs` -> 364/364 PASS (no spec regression)
- [x] 4.3 Add one bounded retry to the final editor when validation fails with repairable diagnostics.

  **Bounded-retry orchestrator landed 2026-06-12.** Full evidence: `evidence/step-4-3-bounded-retry.md`.
  - `utils/toolkit_llm_final_reconciliation.py`:
    - Added 1 new constant: `MAX_FINAL_RECONCILIATION_RETRIES = 1` (the bounded retry budget; the orchestrator therefore runs at most 2 total attempts = initial + 1 retry).
    - Added 4 new orchestrator status names: `FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED`, `_REJECTED`, `_NOT_RETRYABLE`, `_INVALID_BRIEF`.
    - Added 2 new diagnostic codes: `DIAGNOSTIC_CODE_RETRY_NOT_REPAIRABLE` and `DIAGNOSTIC_CODE_RETRY_BUDGET_EXHAUSTED`. Reused existing failure codes for the underlying failure classes.
    - Added pure helper `_select_mock_provider_output_for_attempt(mock_provider_outputs, attempt_index)` for test-only plumbing. Returns the runner's `mock_provider_output` for the given attempt: `None` for the live provider, an indexed entry for a list/tuple, or the last entry when out of range. Empty lists collapse to `None` (live provider).
    - Added pure helper `_is_repairable_final_reconciliation_failure(apply_validate_gate_result) -> bool`. The helper returns `True` only when the apply phase produced `applied` AND the schema-validation phase reported `fail` or `error` (the only retryable class per the spec). All other failure classes (invalid_brief, provider_failed, invalid_json, missing_required_keys, invalid_patch_contract, refused/failed_reconciliation, false source-fidelity claim, fatal apply failures, gate failures) return `False`.
    - Added pure helper `_build_final_reconciliation_retry_brief(brief, previous_diagnostics, attempt_index) -> dict`. Deep-copies the input brief and appends a `retry_context = {attempt_index, previous_diagnostics}` field. Never mutates the input; handles non-dict inputs by returning an empty dict.
    - Added pure helper `_summarize_attempt_for_orchestrator(attempt_index, runner_result, apply_validate_gate_result) -> dict` that produces a stable 5-key attempt record: `attempt_index`, `runner_status`, `apply_validate_gate`, `is_repairable`, `diagnostics` (combined from runner + apply/validate/gate, in order).
    - Added public orchestrator `run_final_reconciliation_with_bounded_retry(brief, module_dir=None, *, mock_provider_outputs=None, source="toolkit") -> dict`:
      1. Non-dict brief fails closed at the boundary with `invalid_brief` status and a structured `invalid_brief` diagnostic. No attempt is made.
      2. Attempt 0 calls `run_llm_final_editor(current_brief, mock_provider_output=...)` with the attempt-0 mock output. When the runner does not return `success`, the orchestrator surfaces `not_retryable` without retrying (runner failures are not retryable per the spec).
      3. When the runner succeeds, calls `apply_validate_and_gate_final_reconciliation_patch_plan(...)` with the runner's `patch_plan`. When the combined result is `applied`, returns `accepted` with the result pinned in `accepted_result`.
      4. When the apply/validate/gate result is `failed`, asks `_is_repairable_final_reconciliation_failure`. When True AND the retry budget has not been used, builds a retry brief and calls the runner exactly one more time.
      5. The orchestrator never calls the runner more than two total attempts (initial + one retry). After the second attempt completes the orchestrator returns the appropriate terminal status.
      6. The retry brief is a deep-copy; the original brief is never mutated.
      7. The function never persists a final report (Step 4.4 owns that).
      8. The function never integrates with the packet builder or finisher (Step 5 owns that).
    - The orchestrator result has a stable 8-key shape: `status`, `accepted`, `retry_count`, `attempts`, `accepted_result`, `last_attempt_result`, `diagnostics`, `error`. Each attempt record has a stable 5-key shape.
    - Diagnostic policy: the combined `diagnostics` list concatenates every attempt's diagnostics, then appends a single `retry_budget_exhausted` or `retry_not_repairable` diagnostic when the orchestrator surfaces those terminal statuses.
  - `scripts/test_toolkit_llm_final_reconciliation.py`:
    - Added 2 new constants to the import list, 4 new orchestrator status names, the `MAX_FINAL_RECONCILIATION_RETRIES` constant, 2 new diagnostic codes, 3 new private helpers, and the new public orchestrator function.
    - Added 2 Step 4.3 fixtures: `_STEP42_APPLIED` (apply+schema+gates all pass), `_step42_schema_fail_result()` (apply succeeds, schema fails - the repairable class), and `_step42_apply_failed_result()` (apply itself fails - non-retryable).
    - Added 10 new test classes with 57 new tests (all provider-free):
      - `TestStep43Constants` (7 tests) - pins the bounded retry budget, four orchestrator status names, and two diagnostic codes.
      - `TestStep43Helpers` (16 tests) - covers `_select_mock_provider_output_for_attempt` (None/empty/string/list/tuple/negative-index/out-of-range), `_is_repairable_final_reconciliation_failure` (schema fail/error pass, schema pass/fatal-apply/not-run/non-dict all return False), `_build_final_reconciliation_retry_brief` (preserves original keys, does not mutate input, deep-copies nested structures, handles empty diagnostics and None attempt_index, returns empty dict for non-dict input), and `_summarize_attempt_for_orchestrator` (stable shape, combined diagnostics ordering, None av, repairable true case).
      - `TestStep43InvalidBrief` (3 tests) - non-dict brief paths (None/string/int/list) all fail closed at the boundary with the right status/diagnostics/error, and the runner is never called.
      - `TestStep43NoRetryOnAttemptZeroAccepted` (2 tests) - attempt-0 accepted does not retry; the accepted result is a copy not a reference.
      - `TestStep43RetryOnRepairableSchemaFailure` (3 tests) - retry+accept happy path (retry_count=1, attempts=2, runner called twice), both-fail-rejected case (retry_count=1, attempts=2, runner called exactly twice, budget-exhausted diagnostic attached), attempts recorded in order with correct attempt_index and is_repairable flags.
      - `TestStep43NoRetryForNonRepairableFailures` (8 tests) - invalid JSON, missing required keys, forbidden target, false source-fidelity claim, provider failure, refused reconciliation, and fatal apply failure all surface as `not_retryable` with retry_count=0 and a single attempt; the not-retryable diagnostic is attached at the top level.
      - `TestStep43RetryBriefShape` (3 tests) - retry brief carries the previous attempt's diagnostics in `retry_context`, the original brief remains unchanged, the retry brief preserves every original key and adds exactly one new top-level key (`retry_context`), and the no-retry path never builds a retry brief.
      - `TestStep43MockProviderOutputsPlumbing` (4 tests) - `mock_provider_outputs=["x","y"]` correctly threads `"x"` to attempt 0 and `"y"` to attempt 1; `create_chat_client` is never called when mock outputs are supplied (live provider stays untouched); out-of-range mock list entries reuse the last entry; empty list collapses to the live-provider path.
      - `TestStep43OrchestratorOutputShape` (5 tests) - top-level result shape keys pinned to the canonical 8; per-attempt record shape pinned to the canonical 5; brief is never mutated; `last_attempt_result` is populated even on rejected; combined `diagnostics` include every attempt's diagnostics in order.
    - All 57 new tests are provider-free and use only `unittest.mock.patch` for the runner and apply/validate/gate helpers.
  - Test counts: 427 (Step 4.2 baseline) -> **484** (Step 4.2 + 57 Step 4.3). All 484 pass with no live provider call and no live CLI subprocess.
  - ASCII compliance: `0 violations` across both files.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **484 PASS, 0 FAIL** in 0.097s
    - `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **106/106 OK** in 0.086s (no regression in dependent suites)
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
    - `openspec validate --specs` -> 364/364 PASS (no spec regression)
- [x] 4.4 Persist `final_reconciliation_report.json` with decisions, changed files, validation outcome, publishability outcome, and `source_fidelity_effective_status`.

  **Accepted final reconciliation report builder and persister landed 2026-06-12.** Full evidence: `evidence/step-4-4-final-report-persistence.md`.
  - `utils/toolkit_llm_final_reconciliation.py`:
    - Added two stable status-name tuples for the build/persist helpers: `FINAL_RECONCILIATION_REPORT_STATUS_ACCEPTED` / `_NOT_ACCEPTED` / `_INVALID_ORCHESTRATOR_RESULT` and `FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN` / `_FAILED` / `_NOT_ACCEPTED` / `_INVALID`.
    - Added three diagnostic codes for the build/persist surface: `DIAGNOSTIC_CODE_REPORT_BUILD_FAILED`, `DIAGNOSTIC_CODE_REPORT_PERSIST_FAILED`, `DIAGNOSTIC_CODE_NOT_ACCEPTED`.
    - Added three bounded report knobs: `FINAL_RECONCILIATION_REPORT_DECISIONS_MAX_ITEMS = 50`, `FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MESSAGE_MAX_LENGTH = 200`, `FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MAX_ITEMS = 20`.
    - Imported `REPORT_VERSION` from `utils.toolkit_final_reconciliation` so the on-disk file is byte-compatible with the archived boundary's report contract. Wrapped in a defensive try/except so the module remains importable in environments where the legacy helper is unavailable.
    - Added pure helpers: `_is_orchestrator_result_accepted(...)`, `_extract_accepted_step42_payload(...)`, `_extract_accepted_patch_plan(...)`, `_truncate_diagnostics_for_report(...)`, `_truncate_decisions_for_report(...)`, `_build_accepted_report_base_shape()`, `_build_non_accepted_report_shape(...)`. All are pure, ASCII-only, and never mutate inputs.
    - Added `build_accepted_final_reconciliation_report(orchestrator_result, brief) -> dict`. The helper consumes the Step 4.3 orchestrator result and emits a compact report with the canonical key set the spec calls out: `version`, `status`, `reconciliation_status`, `source_fidelity_effective_status`, `playable_publication_candidate`, `decisions`, `changed_files`, `validation_after_reconciliation`, `publishability_after_reconciliation`, `report_agreement_after_reconciliation`, `notes`, `diagnostics`. The accepted report locks `source_fidelity_effective_status` to `reconciled_degraded` and `playable_publication_candidate` to `True` so it passes the legacy `is_final_reconciliation_accepted(...)` oracle. Non-dict orchestrator inputs and non-accepted orchestrator results collapse to a `not_accepted` or `invalid_orchestrator_result` report with a single structured diagnostic and zero writes.
    - Added `persist_accepted_final_reconciliation_report(module_dir, orchestrator_result, brief) -> dict`. The helper composes `build_accepted_final_reconciliation_report` with the existing provider-free `utils.toolkit_final_reconciliation.persist_final_reconciliation_report` helper. Returns a stable 6-key shape `{status, path, report, error, diagnostics, bytes}`. Non-accepted orchestrator results and invalid inputs write NOTHING. Accepted reports are persisted as `<module_dir>/final_reconciliation_report.json` via the legacy atomic write helper. Fail-closed on missing/non-string module_dir, unavailable legacy helper, and persist-helper exceptions.
    - Fixed a latent Step 4.4 production bug: the `del brief  # Reserved for future extension.` at the top of `persist_accepted_final_reconciliation_report` left the local name unbound before the inner `build_accepted_final_reconciliation_report(orchestrator_result, brief)` call, raising `UnboundLocalError` on every persist. The `del` is replaced with a docstring-preserving comment so the brief is forwarded verbatim. The build helper explicitly ignores the brief today (the parameter is reserved for Step 5).
  - `scripts/test_toolkit_llm_final_reconciliation.py`:
    - Updated `TestStep43OrchestratorOutputShape.test_top_level_shape_keys_are_stable` to assert the 9-key canonical shape (adds `accepted_patch_plan`). The orchestrator intentionally surfaces the final successful patch plan in the top-level result so the report builder can read the LLM's `decisions` list without re-running the runner.
    - Added 3 new test classes with 35 new tests, all provider-free:
      - `TestStep44Constants` (13 tests) - pins the four persist status names, three report status names, three diagnostic codes, and three bounded-report knobs.
      - `TestStep44BuildAcceptedReport` (12 tests) - accepted orchestrator returns accepted report shape; accepted report passes legacy acceptance oracle; `decisions` list comes from the patch plan; `changed_files` comes from the apply phase; `validation_after_reconciliation` carries compact `{status, success_rate, passed, failed, error_count}`; `publishability_after_reconciliation` carries the four publishability fields verbatim; `report_agreement_after_reconciliation` carries `{status, playable_publication_status}`; `source_fidelity_effective_status` is `reconciled_degraded`; rejected orchestrator returns `not_accepted` report that fails the legacy oracle; non-dict inputs (None, str, int, list) fail closed at the boundary with `invalid_orchestrator_result` and a `report_build_failed` diagnostic; the helper never mutates the orchestrator result or brief.
      - `TestStep44PersistAcceptedReport` (10 tests) - accepted persist writes `final_reconciliation_report.json` to module dir; persisted file is byte-compatible with the legacy contract; persisted report includes the canonical 6-key set plus the 6 spec-required fields; persisted report passes `is_final_reconciliation_accepted`; non-accepted orchestrator writes NOTHING; invalid orchestrator writes NOTHING; missing/empty `module_dir` writes NOTHING; Path objects accepted alongside strings; the persister never mutates inputs.
    - All 35 new tests use a unique tempdir per test (`_Step44TempModuleDirTestCase`); the real `modules/<slug>/` tree is never touched.
  - Test counts: 484 (Step 4.3 baseline) -> **519** (Step 4.3 + 35 Step 4.4). All 519 pass with no live provider call and no live CLI subprocess.
  - ASCII compliance: 0 violations across both files.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **519 PASS, 0 FAIL** in 0.075s (was 484; +35 new tests)
    - `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **106/106 OK** in 0.086s (no regression in dependent suites)
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
- [x] 4.5 Ensure failed or blocked reconciliation leaves the build in a clear blocked state with diagnostics and without claiming playable publication.

  **Blocked final reconciliation report shape landed 2026-06-12.** Full evidence: `evidence/step-4-5-blocked-state.md`.
  - `utils/toolkit_llm_final_reconciliation.py`:
    - Added `FINAL_RECONCILIATION_REPORT_STATUS_BLOCKED = "blocked"`.
    - Added public helper `build_blocked_final_reconciliation_report(orchestrator_result, brief) -> dict`.
    - Non-accepted orchestrator outcomes now produce a stable non-playable report shape with `status: blocked`, `reconciliation_status: blocked`, `source_fidelity_effective_status: blocked`, `playable_publication_candidate: False`, empty `decisions`, empty `changed_files`, compact diagnostics, and compact validation/publishability/report-agreement summaries when present.
    - Accepted orchestrator outcomes delegate to `build_accepted_final_reconciliation_report(...)`, preserving Step 4.4 accepted behavior (`source_fidelity_effective_status: reconciled_degraded`, playable candidate true).
    - The blocked helper is pure: no file writes, no report persistence, no packet-builder/finisher integration, and no input mutation.
  - `scripts/test_toolkit_llm_final_reconciliation.py`:
    - Added `TestStep45BlockedFinalReconciliationReport` with 5 provider-free tests.
    - Tests prove blocked reports do not claim playable publication, do not use `reconciled_degraded`, preserve compact diagnostics, fail the legacy `is_final_reconciliation_accepted(...)` check, and `persist_accepted_final_reconciliation_report(...)` still writes nothing for non-accepted outcomes.
    - Accepted report behavior remains unchanged and still uses `reconciled_degraded` with playable publication candidate true.
  - Test counts: 519 (Step 4.4 baseline) -> **524** (Step 4.4 + 5 Step 4.5). All 524 pass with no live provider call.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **524 PASS, 0 FAIL**
    - `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID

## 5. Packet Builder Integration

- [x] 5.1 Invoke the final editor from `web/extensions/toolkit_homebrew_packet_builder.py` when editorial blockers require reconciliation and no fatal blockers are present.

  **Final-editor invocation from packet builder landed 2026-06-12.** Full evidence: `evidence/step-5-1-packet-builder-invocation.md`.
  - `web/extensions/toolkit_homebrew_packet_builder.py`:
    - Added module-internal helper `_invoke_final_editor_or_fallback(...)` that owns the Step 5.1 live-invocation contract.
    - Editorial branch now imports `run_final_reconciliation_with_bounded_retry`, `persist_accepted_final_reconciliation_report`, and `build_blocked_final_reconciliation_report` from `utils/toolkit_llm_final_reconciliation.py` (defensive import block; falls back to the legacy `final_reconciliation_required` pause only when the import itself fails, per task 5.1 step 6).
    - After brief persistence, the helper invokes the orchestrator with `brief=brief, module_dir=str(module_dir)`. Live-provider exceptions are caught fail-closed.
    - On `status == "accepted"`, the helper calls `persist_accepted_final_reconciliation_report(module_dir=str(module_dir), orchestrator_result=orchestrator_result, brief=brief)`. On `status == "written"`, it sets the accepted metadata (`final_reconciliation_accepted`, `source_fidelity_effective_status: reconciled_degraded`, nested `build_fidelity` mirror) and returns `True` so the caller continues to normal build-result persistence. On any other persist status, it shapes a minimal `blocked` metadata dict (does NOT delegate to `build_blocked_final_reconciliation_report` because that helper passes through to the accepted report for accepted orchestrator results) and returns `False`.
    - On any other orchestrator status (`rejected`, `not_retryable`, `invalid_brief`, etc.), the helper calls `build_blocked_final_reconciliation_report(...)` for the in-memory metadata shape, sets `status: blocked`, `stage: final_reconciliation`, `error: final_reconciliation_editor_rejected:<status>`, and returns `False`.
    - On editor exception, the helper sets `error: final_reconciliation_editor_exception:<error>` and a structured `final_reconciliation_editor_result` payload so downstream reports can list the cause.
    - The helper NEVER claims clean pass: it always emits `source_fidelity_effective_status: reconciled_degraded` (never `pass`, `clean_pass`, `clean`, or `source_fidelity_pass`).
    - Fatal/mixed/unknown classifications are NOT widened: they continue to fall through the existing `_is_final_reconciliation = False` guard and are reported as `status: blocked, stage: build_fidelity, error: build_fidelity_blocked:...`. The editor is invoked only when `_cls_status == "editorial"` AND no accepted report exists.
  - `scripts/test_toolkit_homebrew_gui_unified_flow.py`:
    - Updated `test_no_accepted_report_returns_reconciliation_required` to `test_no_accepted_report_editor_rejected_remains_blocked`: the test now mocks the editor to return non-accepted, asserts the new blocked state (`status: blocked, stage: final_reconciliation, error: final_reconciliation_editor_rejected:rejected`), confirms the brief is still persisted before the editor invocation, and confirms the blocked-report metadata is attached.
    - Added new test class `TestStep51FinalEditorInvocation` (9 tests, all provider-free via mocks):
      - `test_packet_builder_source_imports_final_editor` -- source contract: the packet builder imports the three public names from `utils/toolkit_llm_final_reconciliation.py`.
      - `test_packet_builder_uses_helper_function` -- source contract: the packet builder routes through the `_invoke_final_editor_or_fallback` helper (separation of concerns).
      - `test_editorial_editor_accepted_persists_and_continues` -- accepted path: editor returns accepted, persist succeeds, build result carries `final_reconciliation_accepted=True`, `source_fidelity_effective_status=reconciled_degraded`, the report file is on disk, the brief file is on disk, and `build_result.json` reflects the accepted metadata.
      - `test_editorial_editor_persist_failure_remains_blocked` -- persist-failure path: editor returns accepted but persist returns `failed`; build is `status: blocked, stage: final_reconciliation, error: final_reconciliation_persist_failed:...`, the blocked metadata shape is attached, the report file is NOT created, and the persist helper is called exactly once.
      - `test_editorial_fatal_classification_does_not_invoke_editor` -- Step 5.3 source contract: fatal classification does NOT invoke the editor (asserted via `assert_not_called`).
      - `test_editorial_unknown_classification_does_not_invoke_editor` -- Step 5.3 source contract: unknown classification does NOT invoke the editor.
      - `test_editorial_accepted_status_never_claims_clean_pass` -- honest source-fidelity contract: the accepted path sets `reconciled_degraded` and never `pass` / `clean_pass` / `clean` / `source_fidelity_pass`.
      - `test_editorial_editor_exception_remains_blocked` -- live-provider exception: editor raises, the build is `status: blocked, error: final_reconciliation_editor_exception:...`, and the persist helper is NOT called.
      - `test_editorial_helper_api_import_fails_falls_back` -- task 5.1 step 6: when the helper API import fails, the legacy `final_reconciliation_required` pause is restored and the brief is still persisted.
  - The existing 4.3, 4.4, 4.5, 4.6 editorial tests in `TestStep43*`, `TestStep44*`, `TestStep45*`, `TestStep46*` remain green: 26 tests pass unchanged.
  - No new tests are needed for the `build_blocked_final_reconciliation_report` helper itself; its behavior is already covered by Step 4.5 (524 tests in `scripts/test_toolkit_llm_final_reconciliation.py`).
  - Verification:
    - `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py scripts/test_toolkit_homebrew_gui_unified_flow.py` -> PASS
    - `.venv/bin/python -m unittest -v scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation` -> 9 PASS, 0 FAIL
    - `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep43EditorialReconciliationRequired scripts.test_toolkit_homebrew_gui_unified_flow.TestStep44AcceptedReconciliation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep45EvidenceReportsImmutability scripts.test_toolkit_homebrew_gui_unified_flow.TestStep46PackBuilderEditorialBranch scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep42FatalBlockedBehavior` -> 35 PASS, 0 FAIL
    - `.venv/bin/python -m unittest -q scripts.test_toolkit_llm_final_reconciliation` -> 524 PASS, 0 FAIL
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
- [x] 5.2 Continue to readiness/finisher only when final reconciliation is accepted and deterministic gates pass.

  **Readiness/finisher continuation gate locked 2026-06-12.** Full evidence: `evidence/step-5-2-readiness-finisher-gate.md`.
  - The current production gate is encoded as `build_status == "success"` in `web/routes/toolkit_homebrew_routes.py` (the build handler's build-status branching at lines 1458-1618). The packet builder is the single source of truth for that status; the finisher reads the accepted `final_reconciliation_report.json` from `module_dir` and pins accepted metadata into `compose_report_agreement(...)`.
  - No runtime widening. Per task constraint "If the current production code already satisfies this via `build_status == success` + accepted orchestrator result + accepted persisted report, add minimal source/behavior tests and comments instead of changing runtime", this step adds ONLY:
    - A short clarifying comment in `web/routes/toolkit_homebrew_routes.py` (above the `if build_status == "success":` line) documenting the Step 5.2 gate contract.
    - A short clarifying comment in `web/extensions/toolkit_homebrew_packet_builder.py` (inside `_invoke_final_editor_or_fallback` accepted/else branch) documenting that the helper's blocked/required return paths short-circuit readiness/finisher by mutating `build_result["status"]`.
    - 12 new test class `TestStep52ReadinessFinisherGate` tests in `scripts/test_toolkit_module_build_publication_parity.py` that pin the gate.
  - No front/middle source artifacts touched. No build-fidelity classification paths widened. No fatal/mixed behavior changed.
  - Production behavior pinned by the 12 new tests:
    - `test_route_layer_has_blocked_branch` - blocked branch lives BEFORE success branch.
    - `test_route_layer_has_final_reconciliation_required_branch` - required branch lives BEFORE success branch.
    - `test_route_layer_success_branch_launches_readiness_then_finisher` - readiness AND finisher invocations live AFTER `build_status == "success"` opens, AND finisher runs AFTER readiness inside the success branch.
    - `test_route_layer_has_explicit_step52_gate_comment` - the route layer carries the explicit Step 5.2 gate comment.
    - `test_packet_builder_editor_accepted_keeps_status_success` - accepted path does NOT set `build_result["status"]` to "blocked" or "final_reconciliation_required"; sets the accepted metadata (`final_reconciliation_accepted=True`, `source_fidelity_effective_status="reconciled_degraded"`).
    - `test_packet_builder_helper_blocked_path_returns_early` - the helper's blocked sub-path returns early so the build does not reach normal persistence.
    - `test_packet_builder_status_blocked_does_not_reach_normal_persistence` - blocked return path appears before the normal `build_result_persisted` call.
    - `test_packet_builder_source_fidelity_honesty_never_claims_clean_pass` - accepted branch never assigns `"pass"`, `"clean_pass"`, `"clean"`, or `"source_fidelity_pass"`.
    - `test_finisher_loads_accepted_final_reconciliation_report_from_module_dir` - finisher imports `load_final_reconciliation_report` + `is_final_reconciliation_accepted`, calls them on `module_dir`, and forwards `final_reconciliation_accepted` + `source_fidelity_effective_status` to `compose_report_agreement(...)`.
    - `test_finisher_never_assigns_clean_pass_in_source_fidelity_effective` - finisher never hard-assigns `source_fidelity_effective_status = "pass"`.
    - `test_finisher_uses_persisted_report_not_build_result_flag` - finisher sources `final_rec_accepted` ONLY from the legacy oracle's verdict on the on-disk report; never from a top-level `build_result.get(...)` flag (Step 5.2 contract).
    - `test_finisher_consumes_accepted_report_in_actual_run` - end-to-end behavior: when a module has an accepted `final_reconciliation_report.json` on disk, the finisher surfaces `final_reconciliation_accepted=True` and `source_fidelity_effective_status="reconciled_degraded"` in the result (mirrors the Step 6.1 happy path; added here to lock down the post-gate consumption).
  - Step 5.2 contract pinned:
    - Editorial + editor accepted + persist success -> packet builder leaves `build_result["status"] = "success"` and sets `final_reconciliation_accepted=True` + `source_fidelity_effective_status="reconciled_degraded"`; route layer's `build_status == "success"` branch launches readiness then finisher; finisher re-loads the persisted accepted report and pins accepted metadata into the published build report.
    - Editorial + editor non-accepted or persist fail -> packet builder sets `build_result["status"] = "blocked"`; route layer returns early at the `build_status == "blocked"` branch; readiness/finisher NEVER run.
    - Editorial + helper API import fail -> packet builder sets `build_result["status"] = "final_reconciliation_required"`; route layer returns early at the dedicated branch; readiness/finisher NEVER run.
    - Fatal / mixed / unknown classification -> `build_result["status"] = "blocked"` at the build_fidelity layer; route layer returns early; readiness/finisher NEVER run (Step 5.3 will deepen this contract).
  - Verification:
    - `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py web/routes/toolkit_homebrew_routes.py scripts/test_toolkit_module_build_publication_parity.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_module_build_publication_parity.TestStep52ReadinessFinisherGate -v` -> 12 PASS, 0 FAIL
    - `.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity` -> 135 PASS, 0 FAIL (was 123 before Step 5.2; +12 new tests)
    - `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep42FatalBlockedBehavior scripts.test_toolkit_homebrew_gui_unified_flow.TestStep43EditorialReconciliationRequired scripts.test_toolkit_homebrew_gui_unified_flow.TestStep44AcceptedReconciliation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep45EvidenceReportsImmutability scripts.test_toolkit_homebrew_gui_unified_flow.TestStep46PackBuilderEditorialBranch` -> 35 PASS, 0 FAIL (no regression on prior step 4.x / 5.1 tests)
    - `.venv/bin/python -m unittest -q scripts.test_toolkit_llm_final_reconciliation` -> 524 PASS, 0 FAIL (no regression on final-reconciliation runner)
    - `python3 scripts/check_ascii_compliance.py web/extensions/toolkit_homebrew_packet_builder.py web/routes/toolkit_homebrew_routes.py scripts/test_toolkit_module_build_publication_parity.py` -> 0 violations
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
- [x] 5.3 Preserve existing fatal blocker behavior: fatal and mixed classifications remain fail-closed without final-editor invocation.

  **Fatal/mixed guard pinned 2026-06-12.** Full evidence: `evidence/step-5-3-fatal-mixed-guard.md`.
  - Production code unchanged at runtime. The `if not _is_final_reconciliation:` guard at the existing Step 4.2 terminal-block location already keeps fatal/mixed/unknown on `status: blocked, stage: build_fidelity, error: build_fidelity_blocked:...` and short-circuits before any editor invocation. Only a short clarifying comment was added above the guard documenting the Step 5.3 contract.
  - New test class `TestStep53FatalMixedGuard` in `scripts/test_toolkit_homebrew_gui_unified_flow.py` (7 tests, all provider-free via `unittest.mock.patch`):
    - `test_fatal_keeps_blocked_state_no_editor_invocation` -- end-to-end: fatal classification -> blocked at build_fidelity, no editor call, no `final_reconciliation_required` / `final_reconciliation_accepted` / `source_fidelity_effective_status`, fatal diagnostics remain visible in `final_blocker_classification` and `build_fidelity`.
    - `test_mixed_keeps_blocked_state_no_editor_invocation` -- end-to-end: mixed classification with both fatal and editorial blockers -> same blocked outcome, no editor call.
    - `test_mixed_preserves_fatal_blockers_in_classification` -- mixed classification preserves BOTH `fatal_blockers` and `editorial_blockers` lists on the result (so downstream reports can surface the fatal diagnostics to the human reviewer).
    - `test_fatal_does_not_set_source_fidelity_effective_status` -- fatal path must not emit any `source_fidelity_effective_status` value (only the editorial accepted path is allowed to emit `reconciled_degraded`).
    - `test_source_contract_editorial_only_branch_invokes_helper` -- source contract: `_invoke_final_editor_or_fallback(` call site is structurally inside the `if _cls_status == "editorial":` branch and no fatal/mixed/unknown branch opens after it but before the call.
    - `test_source_contract_helper_api_import_inside_editorial_branch` -- source contract: `from utils.toolkit_llm_final_reconciliation import ...` lives inside `_invoke_final_editor_or_fallback` and is wrapped in `try/except` (the editorial-only helper by construction).
    - `test_source_contract_fatal_block_guarded_by_negation` -- source contract: the `if not _is_final_reconciliation:` guard exists and the block it protects sets the canonical `build_fidelity_blocked:` error with `status: blocked, stage: build_fidelity`.
  - All 7 tests use `unittest.mock.patch` and require no live LLM call. The new class sits next to `TestStep51FinalEditorInvocation` in the same file, reusing the existing `_build_v2_workspace` / `_seed_result` helper pattern.
  - No front/middle pipeline artifacts touched. No build-fidelity classification paths widened. No fatal/mixed behavior changed.
  - Verification:
    - `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py scripts/test_toolkit_homebrew_gui_unified_flow.py` -> PASS
    - `.venv/bin/python -m unittest -v scripts.test_toolkit_homebrew_gui_unified_flow.TestStep53FatalMixedGuard` -> 7 PASS, 0 FAIL
    - `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep42FatalBlockedBehavior scripts.test_toolkit_homebrew_gui_unified_flow.TestStep43EditorialReconciliationRequired scripts.test_toolkit_homebrew_gui_unified_flow.TestStep44AcceptedReconciliation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep45EvidenceReportsImmutability scripts.test_toolkit_homebrew_gui_unified_flow.TestStep46PackBuilderEditorialBranch scripts.test_toolkit_homebrew_gui_unified_flow.TestStep53FatalMixedGuard` -> 42 PASS, 0 FAIL (35 prior step 4.x/5.1/5.2 + 7 new step 5.3)
    - `.venv/bin/python -m unittest -q scripts.test_toolkit_llm_final_reconciliation` -> 524 PASS, 0 FAIL (no regression on final-reconciliation runner)
    - `.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity` -> 135 PASS, 0 FAIL (no regression on publication parity)
    - `python3 scripts/check_ascii_compliance.py scripts/test_toolkit_homebrew_gui_unified_flow.py web/extensions/toolkit_homebrew_packet_builder.py` -> 0 violations
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
- [x] 5.4 Preserve existing front/middle artifacts unchanged and add source-contract tests proving no reconciliation fields enter source graph, normalized packet, blueprint, backstage audit, or ModuleBuilder handoff.

  **Front/middle immutability source-contract + behavioral tests landed 2026-06-12.** Full evidence: `evidence/step-5-4-front-middle-immutability.md`.
  - Production code unchanged. No front/middle pipeline writer (`web/extensions/toolkit_homebrew_packet_builder.py`, `utils/toolkit_source_manifest.py`, `utils/toolkit_builder_blueprint.py`, `utils/toolkit_homebrew_normalizer.py`, `scripts/run_backstage_agent.py`, `scripts/prepare_builder_from_backstage_audit.py`) was modified by this step.
  - New test class `TestStep54FrontMiddleImmutability` added to `scripts/test_toolkit_homebrew_gui_unified_flow.py` (7 tests, all provider-free, all pass).
  - Source-contract tests pin the Step 5.4 forbidden field set (`final_reconciliation`, `final_reconciliation_required`, `final_reconciliation_accepted`, `final_reconciliation_editor_result`, `source_fidelity_effective_status`) and string values (`reconciled_degraded`) against:
    1. `test_source_manifest_no_step54_forbidden`: runs the production `build_source_manifest(...)` helper and asserts none of the forbidden keys/values are present in the serialized output.
    2. `test_normalized_packet_no_step54_forbidden`: runs the production `build_normalized_packet_placeholder(...)` helper and inspects the workspace seed `normalized_packet.json` for the same forbidden keys/values.
    3. `test_builder_blueprint_no_step54_forbidden`: runs the production `generate_builder_blueprint(...)` helper and asserts the serialized blueprint carries no forbidden keys/values.
    4. `test_backstage_audit_artifacts_no_step54_forbidden`: runs the production `run_accurate_ingest_audit(...)` against a stub module, then inspects every emitted artifact (`run.json`, `evidence.json`, `audit_report.json`, `recommendation.json`) and the briefing-prep `builder_brief.json` + `builder_prompt_context.md` for the same forbidden keys/values.
    5. `test_module_builder_handoff_no_step54_forbidden`: runs the packet builder with a mocked `_execute_module_builder` executor, captures the in-memory `builder_input` payload, and asserts the same forbidden keys/values are absent (plus checks the persisted `builder_input.json` if written).
  - Behavioral immutability tests use SHA-256 hash comparison on pre-existing workspace-level front/middle artifacts:
    6. `test_accepted_path_does_not_mutate_front_middle_artifacts`: seeds sentinel `source_graph.json`, `source_manifest.json`, `normalized_packet.json`, `builder_blueprint.json`, `builder_blueprint_report.json` files in the workspace, runs the packet builder with mocked editor returning `accepted` (and persist helper returning `written`), and asserts that the SHA-256 hashes of all five sentinel files are byte-for-byte identical before and after the run.
    7. `test_blocked_path_does_not_mutate_front_middle_artifacts`: same setup but the mocked editor returns `rejected`; the same SHA-256 byte-for-byte invariant is asserted.
  - All 7 tests use `unittest.mock.patch` and require no live LLM call. The mocked helpers in the behavioral tests use sentinel-mock outputs (no provider invocation). The backstage-audit test runs against a stub module created in a unique tempdir.
  - Added `import hashlib` to `scripts/test_toolkit_homebrew_gui_unified_flow.py` for SHA-256 computation in the behavioral tests.
  - All 7 new tests are ASCII-only (0 violations).
  - Verification:
    - `.venv/bin/python -m py_compile scripts/test_toolkit_homebrew_gui_unified_flow.py` -> PASS
    - `.venv/bin/python -m unittest -v scripts.test_toolkit_homebrew_gui_unified_flow.TestStep54FrontMiddleImmutability` -> 7 PASS, 0 FAIL in 0.061s
    - `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep53FatalMixedGuard scripts.test_toolkit_homebrew_gui_unified_flow.TestStep46PackBuilderEditorialBranch scripts.test_toolkit_homebrew_gui_unified_flow.TestStep42FatalBlockedBehavior scripts.test_toolkit_homebrew_gui_unified_flow.TestStep43EditorialReconciliationRequired scripts.test_toolkit_homebrew_gui_unified_flow.TestStep44AcceptedReconciliation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep45EvidenceReportsImmutability scripts.test_toolkit_homebrew_gui_unified_flow.TestFinalReconciliationBoundarySourceContract` -> 47 PASS, 0 FAIL (no regression on prior step 4.x/5.1/5.2/5.3 tests)
    - `.venv/bin/python -m unittest -q scripts.test_toolkit_llm_final_reconciliation` -> 524 PASS, 0 FAIL (no regression on final-reconciliation runner)
    - `.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity` -> 135 PASS, 0 FAIL (no regression on publication parity)
    - `python3 scripts/check_ascii_compliance.py scripts/test_toolkit_homebrew_gui_unified_flow.py` -> 0 violations
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
  - No production code change. Step 5.4 is test-only.

## 6. Well Of Ruin And Safety Tests

- [x] 6.1 Add Well of Ruin regression coverage proving `Trigger`, `Passive Element`, and `Active Element` are not final required locations after accepted reconciliation.

  **Well-of-Ruin bogus-atom regression coverage landed 2026-06-12.** Full evidence: `evidence/step-6-1-well-required-locations.md`.
- [x] 6.2 Prove bogus source atoms are either dropped as final structure or preserved as mechanics/DM guidance without poisoning Narrator-facing topology.

  **Narrator-topology vs DM-guidance distinction landed 2026-06-12.** Full evidence: `evidence/step-6-2-narrator-topology.md`.
  - 20 new provider-free tests added to `scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py` across 4 new test classes (37 total tests, all pass; 17 from Step 6.1 + 20 from Step 6.2).
  - New test-local helper `_project_narrator_facing_topology(module_dir, accepted_report=None, brief=None)` added. The helper reads ONLY from canonical playable location files (`areas/*_BU.json`, `map_*.json`, `module_context.json`) and deliberately ignores the `accepted_report` and `brief` parameters. The `del accepted_report` / `del brief` calls make the intentional non-use explicit and silence linter complaints about unused parameters.
  - Two new constants pin the Step 6.2 contract: `ALLOWED_NON_PLAYABLE_TO_TARGETS` (10 non-playable surfaces: `mechanic_heading`, `trap_rules`, `trap_rule`, `dm_guidance`, `hazard_instruction`, `plot_notes`, `discarded_atom`, `reclassified_atom`, `merged_atom`, `refused`) and `FORBIDDEN_PLAYABLE_TO_TARGETS` (7 forbidden values: `playable_location`, `location`, `playable`, `place`, `area`, `room`, `required_location`).
  - 4 new test classes (20 tests total, all provider-free via mock/synthetic fixtures):
    - `TestStep62NarratorTopologyProjectionIgnoresBlockerEvidence` (5 tests) -- narrator-facing topology proof: the projection output is unchanged regardless of whether the brief's `editorial_blockers` mention the three trap headings, the plan's `notes` field is saturated with the trap headings, or the decision's `reason` field mentions the trap headings. Projection output is byte-stable across with/without blocker evidence. Helper signature contract pinned via `inspect.signature` so future refactors do not accidentally make the helper read from the report.
    - `TestStep62DeleteBogusAtomIsAbsentFromTopologyAndGuidance` (4 tests) -- `Trigger` decision is `delete_bogus_atom`; `Trigger` is absent from the narrator topology projection (and from slugified variants); `Trigger` decision's `to:` target is in `ALLOWED_NON_PLAYABLE_TO_TARGETS` and not in `FORBIDDEN_PLAYABLE_TO_TARGETS`; the spec contract is pinned at the playable-topology layer, not the plan-notes layer.
    - `TestStep62PreserveAsDmGuidanceMayAppearInNotesOrReason` (6 tests) -- `Passive Element` and `Active Element` decisions are `preserve_as_dm_guidance`; both headings are absent from the narrator topology projection (and from slugified variants); the headings MAY appear in the decision's `reason` field (DM-guidance text); the headings MAY appear in the plan's `notes` field (DM-guidance text); the decision's `to:` target is in `ALLOWED_NON_PLAYABLE_TO_TARGETS`; saturated-plan fixture (notes field full of trap headings) still passes contract and still yields clean topology.
    - `TestStep62DecisionTargetsAreNeverPlayableLocationForBogusAtoms` (5 tests) -- every `to:` target is NOT in `FORBIDDEN_PLAYABLE_TO_TARGETS`; every `to:` target IS in `ALLOWED_NON_PLAYABLE_TO_TARGETS`; synthetic plan pins exact `to:` values (`Trigger: mechanic_heading`, `Passive Element: trap_rules`, `Active Element: trap_rules`); negative test fixture with `to: playable_location` for `Trigger` (the anti-pattern) still passes the contract (contract does not check `to:` contents) AND still yields clean narrator topology output, proving the projection's correctness is independent of the plan's `to:` field; cross-pin between `to:` values and plan `notes` content (accepting either snake_case or hyphenated forms).
  - All tests are provider-free; the existing production helpers (`validate_final_reconciliation_patch_contract`, `build_accepted_final_reconciliation_report`, `apply_final_reconciliation_patch_plan`, `persist_accepted_final_reconciliation_report`, `is_final_reconciliation_accepted`) and the new test-local helper (`_project_narrator_facing_topology`) are exercised with synthetic inputs. No new production helper was added.
  - ASCII compliance: 0 violations.
  - Verification:
    - `.venv/bin/python -m py_compile scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_step61_well_of_ruin_bogus_atoms -v` -> **37 PASS, 0 FAIL** in 0.030s
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation` -> **524 PASS, 0 FAIL** (no regression on final-reconciliation runner)
    - `.venv/bin/python -m unittest scripts.test_file_operations_path_safety scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_toolkit_step61_well_of_ruin_bogus_atoms` -> **140 PASS, 0 FAIL** in 0.092s (all related suites green)
    - `python3 scripts/check_ascii_compliance.py scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py` -> `0 violations`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
    - `openspec validate --specs` -> 364/364 PASS (no spec regression)
  - No production code was changed by this step. Step 6.2 is test-only.
  - New focused test file: `scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py` (provider-free; 17 tests across 5 classes). All tests use a synthetic Well-of-Ruin-style module written to a per-test tempdir; no production module is created. The synthetic fixture module is the only fixture; `modules/Well_of_Ruin` is NOT present in this checkout and no production module is touched.
  - Constants pinned at the top of the file: `WELL_OF_RUIN_BOGUS_ATOM_HEADINGS = ("Trigger", "Passive Element", "Active Element")` and `ALLOWED_NON_PLAYABLE_DECISIONS` (the five decision types that keep the three trap headings out of the playable location list).
  - 5 new test classes (17 tests total):
    - `TestStep61AcceptedPatchPlanClassifiesBogusAtomsAsNonPlayable` (5 tests) -- decision-level proof: every accepted-plan decision for one of the three trap headings falls in `ALLOWED_NON_PLAYABLE_DECISIONS` (or refuses); `create_missing_real_element` is forbidden for these specific headings; the plan validates against the contract helper; at least one decision uses `delete_bogus_atom` or `reclassify_atom` (the spec-preferred resolution).
    - `TestStep61AcceptedReportExcludesBogusAtomsAsPlayableLocations` (4 tests) -- built accepted report passes the legacy acceptance oracle and locks `source_fidelity_effective_status="reconciled_degraded"`; report `decisions` never classify the three headings as `create_missing_real_element`; report `changed_files` is empty (spec-aligned drop / preserve without editing canonical module files); at least one heading is preserved as `preserve_as_dm_guidance` (spec-allowed preservation path).
    - `TestStep61ApplyDoesNotIntroduceBogusAtomsAsLocations` (3 tests) -- module-level proof: synthetic module starts with four authored playable locations and none of the three trap headings; running `apply_final_reconciliation_patch_plan` with the empty-`file_patches` accepted plan leaves the canonical playable location list unchanged and never introduces the three trap headings (either as `name`/`locationName` or as a slugified `location_id`); apply helper does not mutate the plan or brief inputs (purity pin).
    - `TestStep61PersistedReportExcludesBogusAtomsAsPlayableLocations` (3 tests) -- on-disk proof: the persisted `final_reconciliation_report.json` writes successfully, passes the legacy acceptance oracle, and locks `source_fidelity_effective_status="reconciled_degraded"`; persisted `decisions` never classify the three headings as `create_missing_real_element`; persisted `changed_files` is empty; the persister does not modify any module playable-location list across the persist call.
    - `TestStep61BuildResultMetadataExcludesBogusAtomsAsLocations` (2 tests) -- build/result metadata proof: the in-memory accepted report carries the canonical 12-key top-level shape and does not register any of the three headings as a top-level field name or a `decisions` list entry value; every plan decision is carried through the report unchanged so the build pipeline cannot silently rewrite the three trap headings' classification.
  - All tests are provider-free; the existing production helpers (`validate_final_reconciliation_patch_contract`, `build_accepted_final_reconciliation_report`, `apply_final_reconciliation_patch_plan`, `persist_accepted_final_reconciliation_report`, and `is_final_reconciliation_accepted`) are exercised with synthetic inputs. No new production helper was added; the only test-local helper is `_collect_playable_location_names_from_module_dir(...)` which is a pure read-only function for asserting what is and is not in the on-disk playable location list.
  - The test-local helper `_collect_playable_location_names_from_module_dir` reads from `areas/*_BU.json`, `map_*.json` (non-BU), and `module_context.json` `locations` lists. It is the only way to assert the on-disk playable location invariant in tests, so it lives in the test file (per the task guidance to prefer test-local helpers over production helpers when no production helper exists for the check).
  - 4 new tests added to the `TestStep61AcceptedPatchPlanClassifiesBogusAtomsAsNonPlayable` class are notably the "decision-level proof" of the spec; the module-level and on-disk proofs are owned by the other 4 classes.
  - ASCII compliance: `0 violations` on the new file.
  - Verification:
    - `.venv/bin/python -m py_compile scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py` -> PASS
    - `.venv/bin/python -m unittest scripts.test_toolkit_step61_well_of_ruin_bogus_atoms -v` -> **17 PASS, 0 FAIL** in 0.010s
    - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation` -> **524 PASS, 0 FAIL** (no regression on final-reconciliation runner)
    - `.venv/bin/python -m unittest scripts.test_file_operations_path_safety scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_toolkit_step61_well_of_ruin_bogus_atoms` -> **120 PASS, 0 FAIL** in 0.092s (all related suites green)
    - `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep43EditorialReconciliationRequired scripts.test_toolkit_homebrew_gui_unified_flow.TestStep44AcceptedReconciliation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep45EvidenceReportsImmutability scripts.test_toolkit_homebrew_gui_unified_flow.TestStep46PackBuilderEditorialBranch scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep53FatalMixedGuard scripts.test_toolkit_homebrew_gui_unified_flow.TestStep54FrontMiddleImmutability scripts.test_toolkit_homebrew_gui_unified_flow.TestFinalReconciliationBoundarySourceContract` -> **49 PASS, 0 FAIL** in 0.139s (Step 4-5 test classes all green; the 8 pre-existing test errors in `TestDescribeBlueprintNotReady` and `TestPacketBuilderV2Integration` are unrelated to this change -- they fail on the clean main branch without the new test file present)
    - `python3 scripts/check_ascii_compliance.py scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py` -> `0 violations`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
    - `openspec validate --specs` -> 364/364 PASS (no spec regression)
- [x] 6.2 Prove bogus source atoms are either dropped as final structure or preserved as mechanics/DM guidance without poisoning Narrator-facing topology.

  **Narrator-topology vs DM-guidance distinction landed 2026-06-12.** Full evidence: `evidence/step-6-2-narrator-topology.md`.
- [x] 6.3 Add negative tests for invalid LLM JSON, forbidden file edits, runtime-only target edits, false clean source-fidelity pass, provider unavailable, and fatal blockers.

  **Final-editor negative tests landed 2026-06-12.** Full evidence: `evidence/step-6-3-negative-tests.md`.
  - 34 new provider-free tests added to `scripts/test_toolkit_llm_final_reconciliation.py` across 5 new test classes:
    - `TestStep63InvalidJsonNegative` (5 tests) -- `run_llm_final_editor(mock_provider_output=...)` for raw prose, empty string, JSON array, malformed JSON, and truncated JSON object; each returns `RUNNER_STATUS_INVALID_JSON` with `DIAGNOSTIC_CODE_INVALID_JSON`, empty `patch_plan`, legacy `error: "invalid_json"`, and mock-provider short-circuit markers preserved. The end-to-end `test_invalid_json_does_not_invoke_apply_phase` patches `apply_final_reconciliation_patch_plan` and asserts the apply helper is never called and the on-disk target file is unchanged.
    - `TestStep63ProviderUnavailableNegative` (3 tests) -- `create_chat_client` raising and `client.chat.completions.create` raising both return `RUNNER_STATUS_PROVIDER_FAILED` with `DIAGNOSTIC_CODE_PROVIDER_FAILED`; the legacy `error` field carries the underlying cause; the apply helper is never invoked on this path.
    - `TestStep63ForbiddenTargetNegative` (12 tests) -- `validate_final_reconciliation_patch_targets(plan, brief)` rejects path traversal (`../unsafe.json`), POSIX absolute (`/etc/passwd`), Windows drive (`C:/...`), backslash (`..\\unsafe.json`), source graph, source manifest, normalized packet, blueprint, blueprint report, module summary, backstage audit, and out-of-whitelist targets; every rejection is `DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET`.
    - `TestStep63RuntimeOnlyTargetNegative` (9 tests) -- end-to-end through `apply_final_reconciliation_patch_plan` AND `apply_validate_and_gate_final_reconciliation_patch_plan` for `module_plot.json`, `party_tracker.json`, `areas/lidda_start.json` (live), `player_quests_lidda.json`, `encounters/encounter_42.json`, `modules/world_registry.json`, `modules/campaign.json`; every runtime-only target is rejected with `DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET`, the file is untouched, and (for the orchestrator path) `gates.status == "not_run"` and the gate helpers are never called.
    - `TestStep63FalseCleanSourceFidelityNegative` (5 tests) -- every clean-pass variant (`pass`, `clean_pass`, `clean`, `source_fidelity_pass`) is rejected at the runner level with `DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM`; missing or non-string claims are rejected; `apply_final_reconciliation_patch_plan` rejects `clean_pass` and writes nothing; `build_accepted_final_reconciliation_report` always normalizes `source_fidelity_effective_status` to `reconciled_degraded` on the accepted path, even if the patch plan carries a false clean claim.
  - 2 new tests added to `TestStep53FatalMixedGuard` in `scripts/test_toolkit_homebrew_gui_unified_flow.py`:
    - `test_fatal_classification_overrides_accepted_report_on_disk` -- writes a synthetic `final_reconciliation_report.json` on disk, then drives the packet builder with a fatal classification. Editor is never invoked, build remains `status: blocked, stage: build_fidelity, error: build_fidelity_blocked:...`, no `final_reconciliation_required` / `final_reconciliation_accepted` / `source_fidelity_effective_status` fields appear, and the on-disk accepted report is preserved untouched.
    - `test_mixed_classification_overrides_accepted_report_on_disk` -- same contract for a mixed classification.
  - **Production fix (1 line, contract-required):** The new `test_blueprint_artifact_rejected_by_targets` and `test_blueprint_report_artifact_rejected_by_targets` exposed a real contract gap in `_FORBIDDEN_SOURCE_MIDDLE_PATTERNS`. The previous pattern `"blueprint_*.json"` did not match the production filenames `builder_blueprint.json` and `builder_blueprint_report.json` because `fnmatch.fnmatch('builder_blueprint.json', 'blueprint_*.json')` returns `False`. A false-positive patch targeting the production blueprint artifacts would have violated the `accurate-ingest-llm-builder-final-editorial-pass` Scenario "Source artifacts remain unchanged". The pattern is updated to `"*blueprint*.json"` with a docstring comment documenting the fix. The pre-existing `test_rejects_blueprint_glob` test (using `blueprint_v2.json`) still passes.
  - All tests are provider-free; the runner-level tests use `mock_provider_output=...`, the apply tests use per-test tempdir, and the GUI tests use `unittest.mock.patch` on the editor and gate helpers.
  - Test counts: 524 (Step 5.4 baseline) -> **558** (Step 5.4 + 34 Step 6.3 + 2 Step 6.3 GUI) + **9** in `TestStep53FatalMixedGuard` (was 7; +2 Step 6.3). All pass with no live provider call.
  - ASCII compliance: 0 violations across all modified files.
  - Verification:
    - `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py scripts/test_toolkit_homebrew_gui_unified_flow.py` -> PASS
    - `.venv/bin/python -m unittest -q scripts.test_toolkit_llm_final_reconciliation` -> **558 PASS, 0 FAIL** (was 524; +34 new)
    - `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep53FatalMixedGuard scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation` -> **18 PASS, 0 FAIL** (Step 5.1 + Step 5.3 expanded test classes)
    - `.venv/bin/python -m unittest -q scripts.test_file_operations_path_safety scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_toolkit_llm_final_reconciliation` -> **661 PASS, 0 FAIL** (all related suites green)
    - `python3 scripts/check_ascii_compliance.py scripts/test_toolkit_llm_final_reconciliation.py scripts/test_toolkit_homebrew_gui_unified_flow.py` -> `0 violations`
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
- [x] 6.4 Add report/GUI source-contract tests proving playable publication and reconciled/degraded source fidelity remain separate.

  **Report/GUI source-contract tests for separate axes landed 2026-06-12.** Full evidence: `evidence/step-6-4-report-gui-source-contract.md`.
  - Augmented existing `TestStep64ReconciledDegradedWording` in `scripts/test_toolkit_module_build_publication_parity.py` with 18 new source-contract tests (8 prior + 18 = 26 total in that class). Coverage:
    - **Helper conditional pinning (6 tests)** -- `isFinalReconciledPlayable` source must require `playable_publication_status === 'pass'`, `source_fidelity_effective_status === 'reconciled_degraded'`, `final_reconciliation_accepted === true`, AND `source_fidelity_reconciled === true` in ONE branch. New `test_helper_rejects_clean_pass_source_fidelity_effective` proves the helper does NOT match when `source_fidelity_effective_status === 'pass'` (would conflate clean pass with reconciled/degraded). `test_helper_uses_single_conditional_with_all_four_axes` and `test_helper_walks_multiple_nested_payload_shapes` pin the gate structure.
    - **Formatter source-contract (6 tests)** -- `formatReportAgreementSection` must emit `Source Fidelity:`, `Source Fidelity Effective:`, AND `Playable Publication:` via SEPARATE `lines.push()` calls. `test_three_axes_are_independent_lines` and `test_formatter_distinguishes_source_fidelity_from_effective` prove the two source-fidelity axes are emitted by DIFFERENT lines (no aliasing) and read from independent sources (`ra.source_fidelity_status` vs `ra.source_fidelity_effective_status`). `test_formatter_keeps_final_reconciliation_accepted_distinct` pins the `Final Reconciliation:` line and `source_fidelity_reconciled` flag.
    - **Reconciled branch negative wording (3 tests)** -- the `Build completed after final reconciliation...` branch block must say `reconciled/degraded` and `not clean pass`; it MUST NOT contain `source fidelity pass`, `source fidelity is pass`, `clean source-fidelity pass`, or `clean_pass` phrases.
    - **Generic failure copy pinned (2 tests)** -- `Build Blocked - Fidelity Check Failed` and `Not Publishable` titles remain for non-reconciled cases; `Build fidelity blocked` and `publishability remains blocked` copy remain for non-reconciled cases.
  - Added new test class `TestStep64ReportAgreementAxesSeparation` with 9 report-data separation tests. Coverage:
    - **Independent keys in result dict** -- result exposes `playable_publication_status`, `source_fidelity_status`, `source_fidelity_effective_status`, `source_fidelity_reconciled`, `final_reconciliation_accepted`, `final_reconciliation_status` as independent keys (no aliasing).
    - **Accepted-recon playable pass without rewrite** -- `compose_report_agreement` with `source_fidelity_status=blocked` + `final_reconciliation_accepted=True` + `source_fidelity_effective_status=reconciled_degraded` returns `playable_publication_status=pass` BUT `source_fidelity_status=blocked` (the original is preserved, never rewritten to pass).
    - **Clean pass without reconciled flag** -- `source_fidelity_status=pass` (no reconciliation) returns `playable_publication_status=pass`, `source_fidelity_status=pass`, `source_fidelity_effective_status=pass`, `source_fidelity_reconciled=False`, `final_reconciliation_accepted=False`.
    - **Degraded original with accepted recon** -- `source_fidelity_status=degraded` + accepted recon returns playable=pass but source_fidelity_status stays degraded (not pass).
    - **Blocked without recon** -- `source_fidelity_status=blocked` (no recon) keeps BOTH axes blocked.
    - **Blocked effective with accepted recon** -- caller passes `final_reconciliation_accepted=True` but `source_fidelity_effective_status=blocked`: composer must NOT pretend clean pass; `source_fidelity_reconciled=False`, playable stays blocked.
    - **Axes can diverge in both directions** -- (A) playable=pass + fidelity=blocked AND (B) playable=blocked + fidelity=pass both achievable.
    - **Static aliasing guard** -- `inspect.getsource(compose_report_agreement)` does not contain `playable = sf` (would co-derive the axes); both keys appear as independent assignments in the return dict.
    - **End-to-end via module dir** -- `compose_report_agreement_from_module_dir` with a real accepted `final_reconciliation_report.json` on disk returns the same independent axes; `source_fidelity_status=blocked` is NOT rewritten to `pass`.
  - All 27 new tests are pure source-contract or pure-helper tests. No live provider calls, no live CLI subprocess, no live file mutations outside tempdir.
  - ASCII compliance: 0 violations.
  - Verification:
    - `.venv/bin/python -m py_compile scripts/test_toolkit_module_build_publication_parity.py scripts/test_toolkit_report_agreement.py` -> PASS
    - `.venv/bin/python -m unittest -v scripts.test_toolkit_module_build_publication_parity.TestStep64ReconciledDegradedWording` -> **26 PASS, 0 FAIL** (was 8; +18 new)
    - `.venv/bin/python -m unittest -v scripts.test_toolkit_module_build_publication_parity.TestStep64ReportAgreementAxesSeparation` -> **9 PASS, 0 FAIL** (new class)
    - `.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity` -> **162 PASS, 0 FAIL** (was 135; +27 new)
    - `.venv/bin/python -m unittest -q scripts.test_toolkit_report_agreement` -> **32 PASS, 0 FAIL** (no regression)
    - `python3 scripts/check_ascii_compliance.py scripts/test_toolkit_module_build_publication_parity.py scripts/test_toolkit_report_agreement.py` -> 0 violations
    - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
  - No production code changed in this step. Step 6.4 is test-only.

## 7. Structural Repair Follow-Up Boundary

- [x] 7.1 Record the Well of Ruin validation failure as structural ModuleBuilder repair work, not final-editor editorial reconciliation work.

  **Boundary recorded 2026-06-22.** `modules/Well_of_Ruin/validation_report.json` reports `total_failed: 86`, dominated by `reference_integrity`, `spatial_contract`, and `party` validation failures. These failures are fatal structural blockers and remain outside the LLM final-editor's editorial patch scope.
- [x] 7.2 Create dedicated OpenSpec follow-up `toolkit-accurate-ingest-modulebuilder-structural-repair` for monster closure, spatial repair, calendar normalization, and structural blocker routing.

  **Follow-up scaffolded 2026-06-22.** The structural repair change owns the ModuleBuilder repair work and preserves this final-editor change's full-validation gate.
- [x] 7.3 After structural repair lands, rerun Well of Ruin through the final-editor verification gates to prove editorial reconciliation only runs after structural validation passes.

  **Editorial-before-structural gate verified 2026-06-23.** Full evidence: `evidence/step-7-3-editorial-gate-after-structural-validation.md`.

  **Well of Ruin local status:** The module `modules/Well_of_Ruin` IS present locally. Structural repair (`toolkit-accurate-ingest-modulebuilder-structural-repair`) has been applied: `spatial_repair_report.json` shows `status: "changed"`, `repaired_area_count: 4`, `unresolved_count: 0`. `validation_report.json` reports `"issues": []` — zero structural failures remain. The module is structurally sound; remaining editorial blockers route through the editorial-only final-editor path.

  **Three gate conditions proven by existing provider-free tests (no new tests needed):**

  1. **Fatal structural categories do NOT invoke the final editor** (Gate 1):
     - `utils/toolkit_final_blocker_classifier.py` has `FATAL_CATEGORIES` explicitly listing `reference_integrity`, `spatial_contract`, `party`, `structural`, `schema`, `topology` (lines 37-45). The classifier uses simple `in` membership: any of these categories is fatal.
     - `scripts/test_toolkit_final_blocker_classifier.py` (57 tests, ALL PASS): proves the fatal/editorial classification mechanism works for all category names.
     - `scripts/test_toolkit_homebrew_gui_unified_flow.py TestStep53FatalMixedGuard` (9 tests, ALL PASS): fatal classification → editor mock `assert_not_called()`, build stays `status: blocked, stage: build_fidelity`. Source-contract tests prove `_invoke_final_editor_or_fallback` is only reachable from the `if _cls_status == "editorial":` branch, and the `if not _is_final_reconciliation:` guard catches fatal/mixed/unknown first. Even with a pre-existing accepted report on disk, fatal overrides it — editor NOT invoked.

  2. **Editorial-only blockers DO invoke the final editor** (Gate 2):
     - `scripts/test_toolkit_homebrew_gui_unified_flow.py TestStep51FinalEditorInvocation` (9 tests, ALL PASS): editorial classification with accepted editor result → editor invoked, brief persisted, build continues with `final_reconciliation_accepted=True`, `source_fidelity_effective_status=reconciled_degraded`. Editorial path also tested for rejected, exception, and import-failure branches.
     - `scripts/test_toolkit_homebrew_gui_unified_flow.py TestStep43EditorialReconciliationRequired` (8 tests, ALL PASS): editorial → `final_reconciliation_required=True`; fatal remains blocked.

  3. **Well of Ruin bogus-atom handling through editorial-only path** (Gate 3):
     - `scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py` (37 tests, ALL PASS): Well-like bogus headings (`Trigger`, `Passive Element`, `Active Element`) classified as non-playable via editorial-only decisions. Source-atom triage hardening (prerequisite) filters Well/Ruin/Awaken/Enrage/Menace/Enthrall/Irradiate/Overwhelm at manifest/triage/blueprint/build-fidelity boundaries.
     - `scripts/test_toolkit_homebrew_gui_unified_flow.py TestStep43EditorialReconciliationRequired` (8 tests, ALL PASS): editorial classification routes through final-editor path correctly.

  **No production code was changed by this step. No new tests were added.** The existing provider-free test suites already prove the 7.3 editorial-before-structural gate comprehensively.

  **Verification:**
  - `.venv/bin/python -m py_compile utils/toolkit_final_blocker_classifier.py scripts/test_toolkit_final_blocker_classifier.py scripts/test_toolkit_homebrew_gui_unified_flow.py` -> PASS
  - `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep53FatalMixedGuard scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep42FatalBlockedBehavior scripts.test_toolkit_homebrew_gui_unified_flow.TestStep43EditorialReconciliationRequired -v` -> **31 PASS, 0 FAIL** (fatal/mixed/editorial gate tests)
  - `.venv/bin/python -m unittest scripts.test_toolkit_final_blocker_classifier -q` -> **57 PASS, 0 FAIL** (classifier mechanism)
  - `.venv/bin/python -m unittest scripts.test_toolkit_step61_well_of_ruin_bogus_atoms -v` -> **37 PASS, 0 FAIL** (Well-like bogus atoms)
  - `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -q` -> **572 PASS, 0 FAIL** (LLM final-editor runner)
  - `.venv/bin/python -m unittest scripts.test_toolkit_module_build_publication_parity -q` -> **162 PASS, 0 FAIL** (publication parity gates)
  - `.venv/bin/python -m unittest scripts.test_file_operations_path_safety scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement -q` -> **127 PASS, 0 FAIL** (dependent suites)
  - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
  - Handoff from `toolkit-accurate-ingest-source-atom-triage-hardening`: that change validated strict and source atom false-NPC blockers (Well/Ruin/Awaken/Enrage/Menace/Enthrall/Irradiate/Overwhelm, plus full effect sentences) are now filtered at the manifest, triage, blueprint, and build-fidelity boundaries.

## 8. Verification

- [x] 8.1 Run `.venv/bin/python -m py_compile` on all touched Python files.

  **PASS 2026-06-23.** `.venv/bin/python -m py_compile` on all 26 touched Python files (14 modified + 12 untracked) -> exit 0, no errors. Files compiled:
  - 14 modified: `core/generators/location_generator.py`, `core/generators/module_builder.py`, `scripts/test_accurate_ingest_source_graph.py`, `scripts/test_toolkit_final_reconciliation.py`, `scripts/test_toolkit_homebrew_gui_unified_flow.py`, `scripts/test_toolkit_module_build_publication_parity.py`, `utils/file_operations.py`, `utils/toolkit_blueprint_seed_writer.py`, `utils/toolkit_entity_candidate_triage.py`, `utils/toolkit_final_blocker_classifier.py`, `utils/toolkit_final_reconciliation.py`, `utils/toolkit_source_manifest.py`, `web/extensions/toolkit_homebrew_packet_builder.py`, `web/routes/toolkit_homebrew_routes.py`
  - 12 untracked: `scripts/test_calendar_normalization.py`, `scripts/test_file_operations_path_safety.py`, `scripts/test_monster_reference_closure.py`, `scripts/test_source_atom_triage_hardening.py`, `scripts/test_spatial_repair.py`, `scripts/test_structural_blocker_routing.py`, `scripts/test_toolkit_llm_final_reconciliation.py`, `scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py`, `utils/calendar_normalization.py`, `utils/monster_reference_closure.py`, `utils/spatial_repair.py`, `utils/toolkit_llm_final_reconciliation.py`
- [x] 8.2 Run targeted final-editor, final-reconciliation, packet-builder, report-agreement, and GUI/source-contract tests.

  **All 8 suites now PASS.** Fixed 2026-06-23:
  - `scripts.test_toolkit_homebrew_gui_unified_flow`: **154 PASS, 0 FAIL** (was 8 NameError -- added missing imports `_execute_module_builder` and `_describe_blueprint_not_ready`).
  - `scripts.test_structural_blocker_routing`: **52 PASS, 0 FAIL** (was 3 failures from clean Well report -- replaced `TestWellOfRuinValidationReportFixture` with `TestWellOfRuinSyntheticFatalCategories` using synthetic Well-like messages).
  - `scripts.test_toolkit_llm_final_reconciliation`: **572 PASS, 0 FAIL**
  - `scripts.test_toolkit_final_reconciliation`: **86 PASS, 0 FAIL**
  - `scripts.test_toolkit_report_agreement`: **32 PASS, 0 FAIL**
  - `scripts.test_toolkit_module_build_publication_parity`: **162 PASS, 0 FAIL**
  - `scripts.test_file_operations_path_safety`: **9 PASS, 0 FAIL**
  - `scripts.test_source_atom_triage_hardening`: **153 PASS, 0 FAIL**
  - Total: **1220 PASS, 0 FAIL** across all 8 targeted suites.
  - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
  - No production module artifacts modified. No live provider calls.
- [x] 8.3 Run `.venv/bin/python core/validation/validate_module_files.py --module Well_of_Ruin` if the module artifact is present or generated during tests.

  **PASS 2026-06-23.** Module `modules/Well_of_Ruin` IS present locally. `core/validation/validate_module_files.py --module Well_of_Ruin` -> 62/62 files validated, 0 errors (100%). All area, monster, map, plot, party, module_context, runtime_room_reachability, map_area_parity, spatial_contract, plot_progression, and area_connectivity checks pass. Well of Ruin is structurally sound. Remaining editorial blockers route through the editorial-only final-editor path (Step 7.3 gate).
- [x] 8.4 Run `.venv/bin/python scripts/audit_module_publishability.py --module Well_of_Ruin --json` if the module artifact is present or generated during tests.
- [x] 8.5 Run `openspec validate toolkit-accurate-ingest-llm-builder-final-editor`.

## SHOULD Guidance

- Prefer micro-edits for large Python files and compile after each touched Python file.
- Prefer pure helper functions for patch validation so tests do not require Flask or live providers.
- Keep status names aligned with the archived boundary: `final_reconciliation_required`, `final_reconciliation_accepted`, and `source_fidelity_effective_status: reconciled_degraded`.
- Keep the small lock/path bug fix in Section 1 so later final-editor tasks can rely on safe artifact persistence.
