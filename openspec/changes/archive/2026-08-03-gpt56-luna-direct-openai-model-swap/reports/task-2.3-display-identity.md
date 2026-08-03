# Task 2.3 Display Identity Verification for gpt-5.6-luna

Timestamp (UTC): 2026-08-03T03:10:00Z
Change: gpt56-luna-direct-openai-model-swap
Task: 2.3 Add the `gpt-5.6-luna` human-readable display mapping and verify model-selection diagnostics report the exact selected model ID.

## 1. Change Applied

`utils/ai_client_factory.py` - `get_model_display_name()` display map: added two additive entries (exact direct-OpenAI ID plus its OpenRouter-prefixed alias for parity with the existing GPT-5.4 Mini entries):

- `"gpt-5.6-luna": "GPT-5.6 Luna"`
- `"openai/gpt-5.6-luna": "GPT-5.6 Luna"`

All existing display mappings (Kimi K2.5, Claude 3.5 Sonnet, Gemini 2.0 Flash, GPT-4.1 family, GPT-5.4 Mini) are preserved unchanged. No provider routing, GPT-5 shim logic, or profile code was touched; the `startswith("gpt-5")` family detection already covers Luna with no Luna-specific branch (per design decision).

## 2. Provider-Free Verification

No live provider/API calls were made; imports load configuration only.

Verification command:

```bash
.venv/bin/python -c "from utils.ai_client_factory import get_chat_model_name, get_model_display_name; assert get_chat_model_name() == 'gpt-5.6-luna'; assert get_model_display_name() == 'GPT-5.6 Luna'; print('display identity PASS')"
```

Result:

```
display identity PASS
```

- `get_chat_model_name()` returns the exact selected model ID `gpt-5.6-luna`. `config.py` does not define `LLM_PROVIDER`, so the helper falls back to the direct-OpenAI default and returns `DM_MAIN_MODEL` (`model_config.py` line 5, `gpt-5.6-luna` from task 1.2).
- `get_model_display_name()` returns `GPT-5.6 Luna` for both the bare ID and the `openai/`-prefixed alias.

## 3. Model-Selection Diagnostics

`get_provider_status()` records the selected model via `get_chat_model_name()` and the human-readable label via `get_model_display_name()` (utils/ai_client_factory.py lines 324-325). Provider-free diagnostics check:

```bash
.venv/bin/python -c "from utils.ai_client_factory import get_provider_status; s = get_provider_status(); print(s['model'], s['model_display'], s['configured_provider'])"
```

Result:

```
gpt-5.6-luna GPT-5.6 Luna openai
```

- `model` = `gpt-5.6-luna` (exact selected model ID, satisfying the Active model identity observability requirement: "model-selection diagnostics SHALL record `gpt-5.6-luna` as the selected model").
- `model_display` = `GPT-5.6 Luna` (Luna-specific human-readable label).
- `configured_provider` = `openai` (direct OpenAI; OpenRouter path untouched).

## 4. No Unrelated Changes

- `git diff -- utils/ai_client_factory.py` shows only the two additive display-map lines (diff below is limited to the mapping change).
- No changes to `model_config.py` (beyond the pre-existing task 1.2 model-ID swap), OpenRouter settings, GPT-5 shim logic, prompt files, or tests in this task.

## 5. Conclusion

Task 2.3 verified: `gpt-5.6-luna` has a human-readable display mapping (`GPT-5.6 Luna`), `get_chat_model_name()` resolves the exact model ID `gpt-5.6-luna` for the active direct-OpenAI configuration, and `get_provider_status()` diagnostics report the exact selected model ID with the Luna label. All checks were provider-free; contract fixtures are intentionally deferred to task 3.x per scope.
