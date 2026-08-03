## 1. Baseline And Model Configuration

- [x] 1.1 Record the current direct-OpenAI provider setting, active GPT-5 model assignments, and baseline results for the targeted GPT-5 contract tests.
- [x] 1.2 Replace every active `gpt-5.4-mini-2026-03-17` runtime assignment in `model_config.py` with the exact direct-OpenAI model ID `gpt-5.6-luna`, including `GPT5_MINI_MODEL` and `GPT5_FULL_MODEL`; leave OpenRouter model settings unchanged.
- [x] 1.3 Verify that `config.py` continues to load the updated assignments through its existing model configuration import and that no persisted game-state or module artifact requires migration.

## 2. Shim And Runtime Alignment

- [x] 2.1 Verify that `utils/ai_client_factory.py` routes `gpt-5.6-luna` through the existing GPT-5-family parameter helper without adding a Luna-specific branch.
- [x] 2.2 Confirm that narrator and combat task profiles produce medium reasoning, validation profiles produce the existing low reasoning/verbosity settings, and configured retries retain high reasoning escalation.
- [x] 2.3 Add the `gpt-5.6-luna` human-readable display mapping and verify model-selection diagnostics report the exact selected model ID.
- [x] 2.4 Audit direct-OpenAI call sites using the changed constants; minimally route only blocking GPT-5.6 calls through the shared helper, preserving non-GPT-5 temperature behavior and leaving unrelated low-traffic migration work deferred.
- [x] 2.5 Add source-contract coverage proving the OpenRouter model ID and OpenRouter-specific `thinking` request shape remain unchanged.

## 3. Contract And Regression Tests

- [x] 3.1 Update the active GPT-5 contract fixtures and docstrings to exercise `gpt-5.6-luna` while preserving generic GPT-5-family assertions.
- [x] 3.2 Add or update provider-free tests for Luna model selection, medium narrator/combat parameters, low validation parameters, high retry parameters, display identity, and legacy sampling omission.
- [x] 3.3 Compile all modified Python files and run the targeted GPT-5 shim, narrator, combat, and routing regression suites with `.venv/bin/python`.

## 4. Direct OpenAI Smoke And Rollout Verification

- [x] 4.1 Run one bounded direct-OpenAI narrator request using `gpt-5.6-luna` and verify successful parameter acceptance, valid response content, selected-model logging, latency, and token telemetry without exposing credentials.
- [x] 4.2 Run one bounded direct-OpenAI combat request and verify valid JSON/action output, existing timeout protection, and no GPT-5.4 fallback.
- [x] 4.3 Perform a short single-player and TABLETOP MODE smoke check after a clean server restart; confirm both modes select Luna and preserve existing gameplay behavior.
- [x] 4.4 Record rollback instructions and any observed latency or provider limitations; if Luna is unavailable or rejects the request contract, restore the prior model assignments and rerun the targeted regression suite.
