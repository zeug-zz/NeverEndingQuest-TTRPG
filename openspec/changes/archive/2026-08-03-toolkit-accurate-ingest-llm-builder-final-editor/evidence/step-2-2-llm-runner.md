# Step 2.2 Evidence: LLM Final-Editor Runner Scaffold

Date: 2026-06-11

## 1. Files Added

- `utils/toolkit_llm_final_reconciliation.py` (new, ~280 lines)
- `scripts/test_toolkit_llm_final_reconciliation.py` (new, ~340 lines, 27 tests across 7 classes)

## 2. Files Modified

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 2.2 checked off with completion notes)

## 3. Files Read (Context)

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/proposal.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/design.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-llm-builder-final-editorial-pass/spec.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-final-reconciliation-patch-contract/spec.md`
- `prompts/toolkit/final_reconciliation_builder_prompt.txt` (Step 2.1 deliverable)
- `utils/ai_client_factory.py` (existing `create_chat_client`, `get_chat_completion_params`, GPT-5 chat profile)
- `utils/toolkit_final_reconciliation.py` (brief/report contract, editable surfaces style)
- `utils/toolkit_homebrew_normalizer.py` (style reference for LLM caller patterns)
- `scripts/test_toolkit_final_reconciliation.py` (style reference for test scaffolding)
- `model_config.py` (`DM_MAIN_MODEL`, `TASK_TEMPERATURES`)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-2-1-final-editor-prompt.md` (Step 2.1 evidence)

## 4. Public Surface

### Constants (exported)

- `FINAL_RECONCILIATION_PROMPT_PATH` -- `Path("prompts") / "toolkit" / "final_reconciliation_builder_prompt.txt"`
- `FINAL_RECONCILIATION_TASK_ID` -- `"toolkit_final_reconciliation"`
- `FINAL_RECONCILIATION_PATCH_VERSION` -- `"accurate_ingest_final_reconciliation_patch.v1"`
- `FINAL_RECONCILIATION_DEFAULT_TEMPERATURE` -- `0.2`
- `FINAL_RECONCILIATION_DEFAULT_TIMEOUT_SECONDS` -- `120`
- `FINAL_RECONCILIATION_PROMPT_FALLBACK` -- short ASCII-only fallback for degraded load environments
- `RUNNER_STATUS_SUCCESS`, `RUNNER_STATUS_PROVIDER_FAILED`,
  `RUNNER_STATUS_PARAM_RESOLUTION_FAILED`, `RUNNER_STATUS_INVALID_BRIEF`
  -- result status names

### Functions (exported)

- `run_llm_final_editor(brief, *, temperature_override=None, timeout_seconds=120)`
  - Final-editor runner that consumes a final reconciliation brief.
  - Returns a structured result dict with `status`, `raw_response_text`,
    `model`, `messages_used`, `params_used`, and `error`.
  - Does NOT mutate the brief, write files, or call packet builder /
    finisher.

### Helpers (exported for tests and downstream steps)

- `_load_final_reconciliation_prompt()` -- loads the on-disk prompt with
  a short ASCII-only fallback when the file is missing/unreadable.
- `_serialize_brief(brief)` -- deterministic ASCII-safe JSON
  serialization (`sort_keys=True`, `ensure_ascii=True`, compact
  separators).
- `_build_chat_messages(brief)` -- returns a 2-message list
  (`system` + `user`) suitable for `client.chat.completions.create`.
- `_extract_response_text(response)` -- best-effort response text
  extraction (returns `""` for malformed responses).
- `_extract_response_model(response, fallback_model)` -- best-effort
  model name extraction (returns the fallback when the response lacks
  a model attribute).

## 5. Behavior Contract

The runner is a thin wiring layer between the brief artifact and the
existing chat-client/model-routing patterns:

1. Reject non-dict briefs with `RUNNER_STATUS_INVALID_BRIEF` (covers
   `str`, `None`, `list`, etc.).
2. Build messages via the read-only helpers. The brief is passed by
   reference but never mutated.
3. Resolve flat Chat Completions kwargs with
   `get_chat_completion_params(FINAL_RECONCILIATION_TASK_ID, DM_MAIN_MODEL, temperature_override=...)`.
   When `model_config` is unavailable, falls back to the literal
   `"gpt-4.1-2025-04-14"` string (same defensive default used inside
   `get_chat_completion_params` itself).
4. Call `client = create_chat_client()` then
   `client.chat.completions.create(messages=..., timeout=..., **params)`.
5. Return a structured result dict with status, raw text, model,
   messages, params, and any error.

Failure modes:

- `param_resolution_failed` when `get_chat_completion_params` raises
  (e.g. misconfigured model_config). The provider is not called.
- `provider_failed` when `create_chat_client` or
  `client.chat.completions.create` raises. The error string is
  captured in `result["error"]`.
- `invalid_brief` when the input is not a dict.

Successful results preserve the model's raw output text, the
response-side `model` attribute (falling back to the resolved params
model), the messages that were sent, and the resolved chat params so
downstream fail-closed validation (Step 2.4) can re-parse them.

## 6. Test Coverage (27 tests, 7 classes)

```
TestFinalReconciliationConstants           5 tests
TestPromptLoading                         2 tests
TestBriefSerialization                    4 tests
TestChatMessageConstruction               5 tests
TestResponseExtractionHelpers             4 tests
TestRunnerPlumbing                        7 tests
                                         ----
Total                                    27 tests
```

### Provider-free behavior tests (20 tests)

- Constants pinned (task id, patch version, prompt path, defaults,
  ASCII-only fallback).
- Prompt loads from disk and contains key contract terms
  (`VALID JSON ONLY`, `source_fidelity_claim`, `editable_surfaces`,
  the patch version, `file_patches`, `decisions`).
- Brief serializer does not mutate, is deterministic, is
  ASCII-compatible, and round-trips through `json.loads` to the same
  dict.
- Chat-message builder emits two messages with `system` then `user`
  roles; the system message contains the contract terms; the user
  message is a labeled, JSON-serializable brief; assembly does not
  mutate the brief.
- Response extractors handle normal responses, missing/empty
  `choices`, and responses without a `model` attribute.

### Runner plumbing tests (7 tests, all mocked)

- `run_llm_final_editor` rejects non-dict briefs
  (`str`, `None`, `list`) with `RUNNER_STATUS_INVALID_BRIEF`.
- `run_llm_final_editor` succeeds end-to-end with a mocked
  `create_chat_client` and fake response; verifies the success
  result shape and that the brief input is not mutated.
- `run_llm_final_editor` returns `RUNNER_STATUS_PROVIDER_FAILED`
  with the simulated error string when the mocked client raises.
- `run_llm_final_editor` returns
  `RUNNER_STATUS_PARAM_RESOLUTION_FAILED` and skips the provider
  call when `get_chat_completion_params` raises.
- The success result does not contain any `written_paths`,
  `files_written`, or `packet` keys (proves no file writes or
  packet-builder integration in this step).

## 7. Style Consistency

The new module follows the conventions in
`utils/toolkit_final_reconciliation.py` and
`utils/toolkit_homebrew_normalizer.py`:

- SPDX license header + module docstring.
- Stable constants near the top of the file.
- Defensive `try/except` around `model_config` import (same pattern
  used in `toolkit_homebrew_normalizer.py`).
- Read-only helpers; the runner never mutates the brief.
- `utils.enhanced_logger` for warning logs (not `print`).
- ASCII-only strings, ASCII-only test names, ASCII-only
  `OPENSPEC` evidence text.
- Test file uses the standard
  `sys.path.append(str(Path(__file__).resolve().parents[1]))` import
  bootstrap.

## 8. Verification Commands Run

```bash
# Compile
.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py
# Result: PASS (no output)

# Tests
.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v
# Result: Ran 27 tests in 0.005s, OK (27 PASS, 0 FAIL)

# ASCII compliance
python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py
# Result: ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0

# OpenSpec strict validation
openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict
# Result: Change 'toolkit-accurate-ingest-llm-builder-final-editor' is valid
```

## 9. Scope Confirmation

This step delivers Step 2.2 only:

- Added the `utils/toolkit_llm_final_reconciliation.py` runner scaffold
  with prompt assembly, deterministic brief serialization, chat-message
  construction, response extraction, and the `run_llm_final_editor(...)`
  runner that wires `create_chat_client()` and
  `get_chat_completion_params(...)` for the
  `toolkit_final_reconciliation` task id.
- Added 27 provider-free tests covering prompt loading, brief
  serialization, message construction, response extraction, and minimal
  runner plumbing with a mocked chat client.
- Updated `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`
  to mark Step 2.2 complete and document verification commands and
  completion evidence.
- Added this evidence file.

Out of scope and not implemented (per task spec):

- No live provider calls.
- No packet-builder or finisher integration.
- No patch contract validation (Section 3).
- No patch application.
- No fail-closed JSON validation of the LLM response (Step 2.4
  widens this with structured diagnostics).
- No comprehensive mock-provider contract (Step 2.3 widens this with
  a stable mock interface for downstream tests).
- No edits to `web/extensions/toolkit_homebrew_packet_builder.py`.
- No writes to module files; the runner is read-only on the brief and
  never touches the filesystem.
