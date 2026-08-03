# Task 3.1 GPT-5 Contract Fixtures Updated to gpt-5.6-luna

Timestamp (UTC): 2026-08-03T05:30:00Z
Change: gpt56-luna-direct-openai-model-swap
Task: 3.1 Update the active GPT-5 contract fixtures and docstrings to exercise `gpt-5.6-luna` while preserving generic GPT-5-family assertions.

## 1. Method

Updated the two active GPT-5 contract test modules in place (file paths preserved for existing unittest/py_compile commands). No runtime code, no `model_config.py`, no `ai_client_factory.py`, no OpenRouter changes, no provider/API calls.

### `scripts/test_gpt54_mini_chat_params_shim.py`

- Module docstring: `GPT-5.4-mini chat parameter shim contract tests.` -> `GPT-5.6 Luna chat parameter shim contract tests (generic GPT-5 family).`
- `test_gpt5_dm_main_omits_legacy_sampling_controls`: fixture model `gpt-5.4-mini-2026-03-17` -> `gpt-5.6-luna`; exact assertion `params["model"]` updated to `gpt-5.6-luna`.
- `test_gpt5_validation_prefers_low_reasoning_and_low_verbosity`: fixture model -> `gpt-5.6-luna`.
- `test_rollback_flag_can_restore_legacy_temperature`: fixture model -> `gpt-5.6-luna`.
- Left unchanged (generic assertions preserved): non-GPT-5 temperature test (`gpt-4.1-2025-04-14`), OpenRouter passthrough shape test, and the hot-path helper source-contract test (`main.py` / `combat_manager.py` / `action_handler.py` must use `get_chat_completion_params`).

### `scripts/test_gpt54_chat_params_contract.py`

- Module docstring: `GPT-5.4 Mini prompt/runtime parity audit.` -> `GPT-5.6 Luna chat-params prompt/runtime parity contract (generic GPT-5 family).`
- `test_gpt5_params_include_reasoning_and_verbosity`: fixture model and exact `params["model"]` assertion -> `gpt-5.6-luna`.
- `test_gpt5_params_exclude_legacy_temperature_by_default`: fixture model -> `gpt-5.6-luna`.
- `test_retry_tier_high_uses_high_reasoning`: fixture model -> `gpt-5.6-luna`.
- Left unchanged (generic assertions preserved): non-GPT-5 temperature preservation (`gpt-4.1-2025-04-14`), narrator/combat shared-helper + timeout source contracts, retry-tier `retry_tier="high"` source contract, and all narrator/combat prompt-pair parity assertions.

## 2. Fixture / generic-contract findings

- All 8 direct GPT-5 fixture strings across the two files now use `gpt-5.6-luna`; zero `gpt-5.4-mini-2026-03-17` fixture strings remain (verified by grep).
- The shim behavior is prefix-based (`startswith("gpt-5")`), so the fixture swap exercises the exact same generic GPT-5-family branch; no Luna-specific conditional is asserted or introduced.
- Generic assertions intentionally preserved: medium reasoning/verbosity for main + combat, low/low for validation, high reasoning on `retry_tier="high"`, legacy `temperature`/`top_p` omitted by default, legacy-temperature restoration via `GPT5_INCLUDE_LEGACY_TEMPERATURE`, non-GPT-5 temperature behavior, OpenRouter `extra_body`/`thinking` passthrough shape, and hot-path helper source contracts.
- Class names (`TestGPT54MiniChatParamsShim`, `TestGPT54ChatParamsContract`) and file names kept as-is for command compatibility; they are identifiers, not stale descriptive claims, and no external references depend on them.

## 3. Commands and results

```bash
.venv/bin/python -m unittest -q scripts.test_gpt54_mini_chat_params_shim scripts.test_gpt54_chat_params_contract
# Ran 16 tests in 0.005s  OK  (EXIT=0)

.venv/bin/python -m py_compile scripts/test_gpt54_mini_chat_params_shim.py scripts/test_gpt54_chat_params_contract.py
# COMPILE PASS (EXIT=0)
```

## 4. Conclusion

Task 3.1 complete. The active GPT-5 contract fixtures and module docstrings now exercise `gpt-5.6-luna` while every generic GPT-5-family assertion (prefix-based routing, reasoning/verbosity profiles, omitted legacy sampling, non-GPT-5 temperature behavior, retry escalation, hot-path helper source contracts) remains intact. No runtime code or OpenRouter coverage was touched.
