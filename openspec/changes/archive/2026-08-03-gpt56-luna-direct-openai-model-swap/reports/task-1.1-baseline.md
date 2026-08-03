# Task 1.1 Baseline - Direct-OpenAI Provider Setting and GPT-5 Model Assignments

Timestamp (UTC): 2026-08-03T02:18:47Z
Change: gpt56-luna-direct-openai-model-swap
Task: 1.1 Record the current direct-OpenAI provider setting, active GPT-5 model assignments, and baseline results for the targeted GPT-5 contract tests.

## 1. Provider Setting

- `model_config.py` line 118: `LLM_PROVIDER = "openai"` (direct OpenAI is the active provider; OpenRouter is not selected).
- `config.py` re-exports model configuration via `from model_config import *` (line 45) and does NOT override `LLM_PROVIDER`, model assignments, or `ENABLE_PROVIDER_FALLBACK`.
- Effective provider at runtime: **direct OpenAI**.
- OpenRouter configuration is present but inactive: `OPENROUTER_CHAT_MODEL = "moonshotai/kimi-k2.5"` (model_config.py line 129). API key values are stored in `config.py` (OPENAI_API_KEY, OPENROUTER_API_KEY) and are intentionally NOT recorded in this report.

## 2. Active GPT-5 Model Assignments (Baseline)

All active direct-OpenAI GPT-5 runtime roles in `model_config.py` currently resolve to the exact model ID `gpt-5.4-mini-2026-03-17`:

- Narrator / main: `DM_MAIN_MODEL` (line 5)
- Summarization: `DM_SUMMARIZATION_MODEL` (line 6)
- Validation: `DM_VALIDATION_MODEL` (line 7)
- Action prediction: `ACTION_PREDICTION_MODEL` (line 10)
- Combat: `COMBAT_MAIN_MODEL` (line 13), `COMBAT_DIALOGUE_SUMMARY_MODEL` (line 17)
- Builders: `NPC_BUILDER_MODEL` (line 20), `MONSTER_BUILDER_MODEL` (line 26)
- Summaries/validators: `ADVENTURE_SUMMARY_MODEL` (line 21), `CHARACTER_VALIDATOR_MODEL` (line 22)
- Updates: `PLOT_UPDATE_MODEL` (line 23), `PLAYER_INFO_UPDATE_MODEL` (line 24), `NPC_INFO_UPDATE_MODEL` (line 25), `ENCOUNTER_UPDATE_MODEL` (line 27), `LEVEL_UP_MODEL` (line 28), `TRANSITION_VALIDATOR_MODEL` (line 31)
- Legacy GPT-5 selectors: `DM_MINI_MODEL` (line 35), `DM_FULL_MODEL` (line 36), `GPT5_MINI_MODEL` (line 43), `GPT5_FULL_MODEL` (line 44)
- Compression: `NARRATIVE_COMPRESSION_MODEL` (line 103), `LOCATION_COMPRESSION_MODEL` (line 104)

Count: 22 active direct-OpenAI GPT-5 model constants, all set to `gpt-5.4-mini-2026-03-17`. No active assignment in `model_config.py` uses any other GPT-5 ID (no date-suffixed alternate branches reference a different GPT-5 model).

## 3. GPT-5 Runtime Detection and Display Identity (Baseline)

- `utils/ai_client_factory.py` `_is_gpt5_model()` (line 28-30): GPT-5-family detection via `str(model_name).lower().startswith("gpt-5")` - generic, covers any `gpt-5*` model including the future `gpt-5.6-luna`, no Luna-specific branch exists.
- `get_model_display_name()` (lines 191-212): current display mapping includes `"gpt-5.4-mini-2026-03-17" -> "GPT-5.4 Mini"` (and `"openai/gpt-5.4-mini-2026-03-17" -> "GPT-5.4 Mini"`). No `gpt-5.6-luna` display entry yet (expected - added later in task 2.3).
- `get_chat_model_name()` (lines 168-188): returns `DM_MAIN_MODEL` for the direct-OpenAI path (provider != "openrouter"), i.e., currently `gpt-5.4-mini-2026-03-17`.

## 4. Targeted GPT-5 Contract Test Baseline

Command:

```bash
.venv/bin/python -m unittest -q scripts.test_gpt54_mini_chat_params_shim scripts.test_gpt54_chat_params_contract
```

Result:

```
Ran 16 tests in 0.005s

OK
```

- `scripts.test_gpt54_mini_chat_params_shim`: PASS (GPT-5-family chat parameter shim contract).
- `scripts.test_gpt54_chat_params_contract`: PASS (GPT-5 chat parameter contract).
- 16 tests total, 0 failures, 0 errors, no provider/API calls (provider-free).

## 5. Notes

- No runtime code was modified for this baseline task. No credentials or raw secret values are recorded above.
- Provider fallback bookkeeping (`ENABLE_PROVIDER_FALLBACK`, `handle_provider_error()`) is unchanged.
- This report serves as the pre-swap baseline; task 1.2 replaces the active assignments with `gpt-5.6-luna` and task 3.x revalidates the contract tests against the new model ID.
