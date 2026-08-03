# Task 2.5 OpenRouter Isolation Source-Contract Coverage

Timestamp (UTC): 2026-08-03T05:05:00Z
Change: gpt56-luna-direct-openai-model-swap
Task: 2.5 Add source-contract coverage proving the OpenRouter model ID and OpenRouter-specific `thinking` request shape remain unchanged.

## 1. Method

Added one focused, provider-free test module: `scripts/test_gpt56_luna_direct_openai_contract.py` (13 tests). No live provider calls, no runtime code edits, no OpenRouter config changes.

Three assertion groups:

1. **OpenRouter constants unchanged** - imports `model_config` and asserts `OPENROUTER_CHAT_MODEL == "moonshotai/kimi-k2.5"`, `OPENROUTER_FULL_MODEL == "moonshotai/kimi-k2.5"`, `OPENROUTER_MINI_MODEL == "google/gemini-2.0-flash-exp"`, and that no `gpt-5.6-luna` ID appears in any of them (no Luna substitution into the OpenRouter path).
2. **OpenRouter branch flat shape** - mocks the factory provider selection (`ai_client_factory._get_actual_provider` -> `("openrouter", True)`) and asserts `get_chat_completion_params(...)` retains the existing flat shape `{model, temperature, thinking}` with no `reasoning_effort`/`verbosity` keys for both task-2.4-edited tasks and a thinking-enabled task.
3. **Task-2.4 callsite routing** - source-contract assertions on `updates/update_encounter.py` and `updates/plot_update.py`: shared `get_chat_completion_params` import and `**get_chat_completion_params(... temperature_override=TEMPERATURE)` call present; `get_model_config` import and the old `model=config["model"]` / `**config.get("extra_body", {})` request construction absent.

## 2. OpenRouter branch verification (mocked provider)

```python
get_chat_completion_params("encounter_update", "gpt-5.6-luna", temperature_override=0.7)
-> {'model': 'moonshotai/kimi-k2.5', 'temperature': 0.7, 'thinking': {'type': 'disabled'}}

get_chat_completion_params("plot_update", "gpt-5.6-luna", temperature_override=0.7)
-> {'model': 'moonshotai/kimi-k2.5', 'temperature': 0.7, 'thinking': {'type': 'disabled'}}

get_chat_completion_params("dm_main", "gpt-5.6-luna", temperature_override=0.7)
-> {'model': 'moonshotai/kimi-k2.5', 'temperature': 0.7, 'thinking': {'type': 'enabled'}}
```

These match the pre-edit OpenRouter shapes recorded in the task-2.4 audit (`OR SHAPE IDENTICAL encounter_update/plot_update`). `reasoning_effort` and `verbosity` never appear on the OpenRouter branch; the `thinking` extra-body payload remains flattened exactly as before.

## 3. Commands and results

```bash
.venv/bin/python -m py_compile scripts/test_gpt56_luna_direct_openai_contract.py
# COMPILE PASS

.venv/bin/python -m unittest -q scripts.test_gpt56_luna_direct_openai_contract
# Ran 13 tests in 0.001s  OK
```

## 4. Conclusion

Task 2.5 complete. The direct-OpenAI gpt-5.6-luna swap leaves OpenRouter model selection (`OPENROUTER_CHAT_MODEL`/`OPENROUTER_FULL_MODEL`/`OPENROUTER_MINI_MODEL`) and the OpenRouter `thinking` request shape byte-for-byte unchanged, and the two task-2.4-edited call sites remain on the shared helper with no `get_model_config` request construction reintroduced.
