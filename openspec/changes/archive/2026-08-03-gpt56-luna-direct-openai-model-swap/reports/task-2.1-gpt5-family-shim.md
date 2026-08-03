# Task 2.1 GPT-5 Family Shim Verification for gpt-5.6-luna

Timestamp (UTC): 2026-08-03T02:26:00Z
Change: gpt56-luna-direct-openai-model-swap
Task: 2.1 Verify that `utils/ai_client_factory.py` routes `gpt-5.6-luna` through the existing GPT-5-family parameter helper without adding a Luna-specific branch.

## 1. Provider-Free Behavior Check

Command:

```bash
.venv/bin/python -c "from utils.ai_client_factory import get_chat_completion_params; p=get_chat_completion_params('dm_main','gpt-5.6-luna'); assert p == {'model':'gpt-5.6-luna','reasoning_effort':'medium','verbosity':'medium'}, p; print('Luna generic GPT-5 shim PASS')"
```

Result:

```
Luna generic GPT-5 shim PASS
```

- `get_chat_completion_params("dm_main", "gpt-5.6-luna")` returns exactly `{'model': 'gpt-5.6-luna', 'reasoning_effort': 'medium', 'verbosity': 'medium'}`.
- The `dm_main` task profile resolves to medium reasoning and medium verbosity (default branch of `_resolve_gpt5_chat_profile()`).
- No `temperature` or `top_p` keys are present by default (`GPT5_INCLUDE_LEGACY_TEMPERATURE = False`, line 25; the legacy-sampling block at lines 554-559 is gated off).
- No provider/API calls were made; the check is fully provider-free.

## 2. Generic Detection - No Luna Branch

Source inspection of `utils/ai_client_factory.py`:

- `_is_gpt5_model()` (lines 28-30): GPT-5-family detection via `str(model_name).lower().startswith("gpt-5")`. This generic prefix check covers `gpt-5.6-luna` without naming it.
- `_resolve_gpt5_chat_profile()` (lines 33-69): task-id-based profiles (validation/action_prediction/updates = low/low; compression = low/low; summary/chronicle/diary = low/medium; default = medium/medium; retry tiers escalate to high). Contains no model-ID conditional at all.
- `get_chat_completion_params()` (lines 530-569): the direct-OpenAI GPT-5 branch (line 552) dispatches purely on `_is_gpt5_model(model)` and calls `_resolve_gpt5_chat_profile()`; OpenRouter keeps its separate `temperature`/`extra_body` path unchanged.
- Grep for `luna|Luna|LUNA` across the file: zero matches. No Luna-specific conditional, constant, or mapping was added.

## 3. Conclusion

Task 2.1 verified: `gpt-5.6-luna` routes through the existing generic GPT-5-family shim with the expected medium/medium parameter shape, legacy sampling omitted by default, and no Luna-specific branch introduced. No runtime code was modified. The display-name mapping for Luna remains deferred to task 2.3 (per design.md section "Reuse GPT-5-family detection instead of adding a Luna branch").
