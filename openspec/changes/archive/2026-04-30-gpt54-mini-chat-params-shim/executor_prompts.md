# Builder Handoff Prompts

These prompts are review artifacts for a future builder pass. They intentionally describe implementation work but do not perform it.

## Step 1.1-1.5 Builder Prompt (full variant)

Implement OpenSpec `gpt54-mini-chat-params-shim` Section 1 only.

Goal: Add the central GPT-5.4-mini Chat Completions parameter shim foundation without adopting it in runtime call sites yet.

Allowed files: `model_config.py`, `utils/ai_client_factory.py`, and a new or existing targeted test file under `scripts/` only if needed for helper contract scaffolding.

Forbidden: Do not edit `main.py`, `core/managers/combat_manager.py`, `core/ai/action_handler.py`, prompts, OpenRouter strategy, model constants, or provider routing. Do not migrate to Responses API. Do not implement `llm.call()`.

Required:
- Add a rollback flag equivalent to `GPT5_INCLUDE_LEGACY_TEMPERATURE = False` with default false.
- Add a task-profile mapping for GPT-5-style Chat Completions parameters.
- Add a helper in `utils/ai_client_factory.py` that returns a flat params dict for `client.chat.completions.create(...)`.
- For model names starting with `gpt-5`, helper output MUST include `reasoning_effort` and `verbosity` and MUST NOT include `temperature` or `top_p` by default.
- For non-GPT-5 models, helper output MUST preserve legacy `TASK_TEMPERATURES` behavior and MUST NOT include GPT-5-only fields.
- Existing `get_model_config()` behavior must remain available.

Constraints:
- Keep the helper additive and easy to absorb into future model profiles.
- Avoid broad imports or circular dependencies.
- Use ASCII-only code/comments.
- Edit Strategy: Apply one anchored patch at a time, then run `python3 -m py_compile` before proceeding.

Verify:
- `python3 -m py_compile model_config.py utils/ai_client_factory.py`
- If a test file is added, run it directly with `.venv/bin/python` when it imports app dependencies.

Output:
- Summarize helper name/signature.
- Show GPT-5 default params example and non-GPT-5 params example.
- Confirm no runtime call sites were modified.

Verification Gate (after builder reports):
- Compile output passes.
- GPT-5 params omit `temperature` and `top_p` by default.
- Non-GPT-5 params preserve temperature.
- No runtime call-site adoption occurred in this step.

Next Step Ready: Step 2.1-2.4 helper contract tests.

## Step 2.1-2.4 Builder Prompt (full variant)

Implement OpenSpec `gpt54-mini-chat-params-shim` Section 2 only.

Goal: Add deterministic helper contract tests before any runtime call-site adoption.

Allowed files: `scripts/test_gpt5_chat_params_shim.py` or the smallest existing relevant test file, plus minimal test-only imports.

Forbidden: Do not edit runtime call sites. Do not change prompts, model constants, OpenRouter strategy, or provider routing.

Required:
- Test GPT-5-style output includes `reasoning_effort` and `verbosity`.
- Test GPT-5-style output omits `temperature` and `top_p` by default.
- Test non-GPT-5 output includes legacy task `temperature` and omits GPT-5-only fields.
- Test rollback flag behavior without changing the default.
- Tests must not require live API calls.

Constraints:
- Prefer monkeypatching module-level constants over editing real config files.
- Keep tests deterministic and offline.
- Use ASCII-only test output.

Verify:
- `python3 -m py_compile model_config.py utils/ai_client_factory.py scripts/test_gpt5_chat_params_shim.py`
- `.venv/bin/python scripts/test_gpt5_chat_params_shim.py`

Output:
- Report test count and pass/fail output.
- Confirm tests are offline and do not instantiate live provider clients.

Verification Gate (after builder reports):
- Tests prove GPT-5 legacy sampling omission.
- Tests prove legacy model compatibility.
- No live API dependency introduced.

Next Step Ready: Step 3.1-3.4 limited high-value adoption.

## Step 3.1-3.4 Builder Prompt (full variant)

Implement OpenSpec `gpt54-mini-chat-params-shim` Section 3 only after Sections 1 and 2 pass.

Goal: Adopt the helper in a small number of high-value gametest call sites without broad migration.

Allowed files: `main.py`, `core/managers/combat_manager.py`, `core/ai/action_handler.py`, and tests/source-contract checks directly related to these call sites.

Forbidden: Do not rewrite all Chat Completions call sites. Do not edit low-traffic scripts/generators unless already using the helper locally. Do not change prompts. Do not alter model constants. Do not migrate to Responses API. Do not implement the v2 router.

Required:
- Replace only local parameter construction in selected narrator/validation/combat/action-helper calls with the central helper.
- Preserve existing messages, model intent, retry behavior, and error handling.
- Document call sites intentionally left unchanged as deferred to the v2 router migration.
- Ensure GPT-5 helper adoption does not pass duplicate `model`, `temperature`, or `top_p` parameters.

Constraints:
- Edit Strategy: Apply one anchored patch at a time, then run `python3 -m py_compile <file>` before the next patch.
- Avoid modifying deeply nested control flow unless necessary.
- If a call site is brittle or ambiguous, leave it unchanged and document deferral.

Verify:
- `python3 -m py_compile main.py core/managers/combat_manager.py core/ai/action_handler.py utils/ai_client_factory.py`
- Run the helper tests from Section 2.
- Run targeted existing regression suites selected by touched paths, such as combat and narrator source-contract tests if available.

Output:
- List each adopted call site by file/function purpose.
- List each intentionally deferred category.
- Include verification command outputs.

Verification Gate (after builder reports):
- Compile output passes.
- Helper tests still pass.
- No broad migration occurred.
- Existing prompt/retry behavior preserved.

Next Step Ready: Step 4.1-4.5 verification and review.

## Step 4.1-4.5 Builder Prompt (standard variant)

Verify OpenSpec `gpt54-mini-chat-params-shim` implementation only.

Goal: Prove the shim is narrow, reversible, and aligned with the v2 router plan.

Allowed: Verification commands, test output capture, and documentation-only notes in this change if needed.

Forbidden: Do not add new runtime behavior during verification. Do not commit or push.

Required:
- Run syntax checks for all touched Python files.
- Run helper contract tests.
- Run targeted narrator/combat regressions if call-site adoption occurred.
- Inspect diffs for forbidden scope creep: Responses API, `llm.call()`, OpenRouter rewrite, broad call-site migration, model constant changes.
- Document any intentionally unchanged call sites.

Verify:
- `git diff --stat`
- `git diff -- model_config.py utils/ai_client_factory.py main.py core/managers/combat_manager.py core/ai/action_handler.py`
- Relevant compile/test commands from prior steps.

Output: PASS/FAIL/NEEDS_FIX with evidence and exact next action.

Verification Gate (after builder reports):
- Scope compliance confirmed.
- Tests pass or failures are clearly classified as pre-existing/unrelated.
- Reviewer can decide whether to archive, revise, or defer adoption.

Next Step Ready: Review decision, then apply/verify/archive through normal OpenSpec workflow.
