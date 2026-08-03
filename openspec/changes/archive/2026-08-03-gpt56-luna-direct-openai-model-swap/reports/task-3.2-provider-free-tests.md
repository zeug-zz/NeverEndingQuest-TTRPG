# Task 3.2 Provider-Free Luna Direct-OpenAI Contract Tests

Timestamp (UTC): 2026-08-03T06:10:00Z
Change: gpt56-luna-direct-openai-model-swap
Task: 3.2 Add or update provider-free tests for Luna model selection, medium narrator/combat parameters, low validation parameters, high retry parameters, display identity, and legacy sampling omission.

## 1. Method

Extended the focused provider-free module created in task 2.5, `scripts/test_gpt56_luna_direct_openai_contract.py`, with 26 new tests across 6 new test classes (13 -> 39 tests). No runtime code, no `model_config.py`, no `ai_client_factory.py`, no OpenRouter changes, and no live provider/API calls.

Coverage added (all assertions provider-free; direct-OpenAI path is deterministic because `model_config.LLM_PROVIDER == "openai"` makes `_get_actual_provider()` return `("openai", False)`):

1. **`TestDirectOpenAIModelSelection` (4 tests)** - every active GPT-5 runtime role constant in `model_config` (`DM_MAIN_MODEL`, `DM_VALIDATION_MODEL`, `COMBAT_MAIN_MODEL`, `GPT5_MINI_MODEL`, `GPT5_FULL_MODEL`, compression/update/builder roles, etc., 22 constants total) equals `gpt-5.6-luna`; no active role contains `gpt-5.4-mini`; `get_chat_model_name()` returns `gpt-5.6-luna`; `_is_gpt5_model("gpt-5.6-luna")` is True (Luna routes through the generic GPT-5-family branch, no Luna-specific conditional).
2. **`TestDirectOpenAIMediumNarratorCombatProfile` (3 tests)** - `get_chat_completion_params("dm_main", "gpt-5.6-luna")` and `combat_main` yield `reasoning_effort="medium"` + `verbosity="medium"`, including when the configured `DM_MAIN_MODEL` constant is passed.
3. **`TestDirectOpenAILowEffortProfiles` (5 tests)** - `validation`, `dm_validation`, `action_prediction`, `updates`, and `compression` all yield `reasoning_effort="low"` + `verbosity="low"`.
4. **`TestDirectOpenAIRetryEscalation` (4 tests)** - `retry_tier="high"` escalates `dm_main`/`combat_main` to `reasoning_effort="high"` while preserving `verbosity="medium"`, keeps validation at `verbosity="low"`, and the `retry` alias also escalates to high.
5. **`TestLunaDisplayIdentity` (3 tests)** - `get_model_display_name()` returns `"GPT-5.6 Luna"` against the real config and when `get_chat_model_name()` is forced to `gpt-5.6-luna`; the display mapping source contains both `gpt-5.6-luna` and `openai/gpt-5.6-luna` entries.
6. **`TestLunaLegacySamplingOmission` (7 tests)** - `temperature` and `top_p` absent for `dm_main`, `combat_main`, `validation`, and high-retry requests; `temperature_override` is NOT applied on the GPT-5 branch; `GPT5_INCLUDE_LEGACY_TEMPERATURE` defaults to False; GPT-5 profile shape is exactly `{model, reasoning_effort, verbosity}`.

Existing coverage kept intact: all 13 task-2.5 OpenRouter isolation tests (constants unchanged, flat `thinking` shape on the OpenRouter branch, task-2.4 callsite helper routing) are unmodified and still pass. The generic non-GPT-5 temperature test and OpenRouter shape tests in `scripts/test_gpt54_mini_chat_params_shim.py` and `scripts/test_gpt54_chat_params_contract.py` were not touched.

## 2. Example verified shapes

```python
get_chat_completion_params("dm_main", "gpt-5.6-luna")
-> {'model': 'gpt-5.6-luna', 'reasoning_effort': 'medium', 'verbosity': 'medium'}

get_chat_completion_params("combat_main", "gpt-5.6-luna")
-> {'model': 'gpt-5.6-luna', 'reasoning_effort': 'medium', 'verbosity': 'medium'}

get_chat_completion_params("validation", "gpt-5.6-luna")
-> {'model': 'gpt-5.6-luna', 'reasoning_effort': 'low', 'verbosity': 'low'}

get_chat_completion_params("action_prediction", "gpt-5.6-luna")
-> {'model': 'gpt-5.6-luna', 'reasoning_effort': 'low', 'verbosity': 'low'}

get_chat_completion_params("compression", "gpt-5.6-luna")
-> {'model': 'gpt-5.6-luna', 'reasoning_effort': 'low', 'verbosity': 'low'}

get_chat_completion_params("dm_main", "gpt-5.6-luna", retry_tier="high")
-> {'model': 'gpt-5.6-luna', 'reasoning_effort': 'high', 'verbosity': 'medium'}

get_chat_completion_params("dm_main", "gpt-5.6-luna", temperature_override=0.7)
-> {'model': 'gpt-5.6-luna', 'reasoning_effort': 'medium', 'verbosity': 'medium'}
   (temperature_override ignored on the GPT-5 branch by default)

get_chat_model_name() -> 'gpt-5.6-luna'
get_model_display_name() -> 'GPT-5.6 Luna'
```

## 3. Commands and results

```bash
.venv/bin/python -m unittest -q scripts.test_gpt56_luna_direct_openai_contract scripts.test_gpt54_mini_chat_params_shim scripts.test_gpt54_chat_params_contract
# Ran 55 tests in 0.005s  OK  (EXIT=0)

.venv/bin/python -m unittest -v scripts.test_gpt56_luna_direct_openai_contract
# Ran 39 tests in 0.001s  OK  (EXIT=0)  -- 13 OpenRouter isolation + 26 direct-Luna

.venv/bin/python -m py_compile scripts/test_gpt56_luna_direct_openai_contract.py
# COMPILE PASS (EXIT=0)

python3 -c "...non-ascii scan..." scripts/test_gpt56_luna_direct_openai_contract.py
# 0 non-ASCII characters (Windows cp1252 safety)
```

## 4. Conclusion

Task 3.2 complete. The focused provider-free suite now covers Luna model selection (all 22 active GPT-5 role constants + `get_chat_model_name()`), medium/medium `dm_main` and `combat_main`, low/low validation/action/compression profiles, high-retry reasoning with preserved verbosity, `get_model_display_name()` identity, and default omission of `temperature`/`top_p` on the GPT-5 branch. All 13 OpenRouter isolation tests from task 2.5 remain intact, the generic GPT-5 shim contract suites still pass (16 tests), and no live provider/API calls were made.
