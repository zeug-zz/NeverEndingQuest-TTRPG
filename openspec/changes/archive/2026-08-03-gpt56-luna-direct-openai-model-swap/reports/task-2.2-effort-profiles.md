# Task 2.2 Effort Profile Verification for gpt-5.6-luna

Timestamp (UTC): 2026-08-03T02:40:00Z
Change: gpt56-luna-direct-openai-model-swap
Task: 2.2 Confirm that narrator and combat task profiles produce medium reasoning, validation profiles produce the existing low reasoning/verbosity settings, and configured retries retain high reasoning escalation.

## 1. Provider-Free Assertions

Command (credentials never involved; no provider/API calls):

```bash
.venv/bin/python -c "from utils.ai_client_factory import get_chat_completion_params; ...assertions..."
```

Result:

```
PASS: 7/7 profile assertions + legacy sampling omission
```

Asserted profile table for `get_chat_completion_params(task_id, "gpt-5.6-luna")`:

| task_id | retry_tier | reasoning_effort | verbosity | Status |
|---------|-----------|------------------|-----------|--------|
| `dm_main` | - | medium | medium | PASS |
| `combat_main` | - | medium | medium | PASS |
| `dm_validation` | - | low | low | PASS |
| `action_prediction` | - | low | low | PASS |
| `narrative_compression` | - | low | low | PASS |
| `dm_validation` | high | high | low (unchanged) | PASS |
| `combat_main` | high | high | medium (unchanged) | PASS |

Additional assertions:

- Legacy sampling omission: no `temperature` or `top_p` keys in either the default `dm_main` params or the escalated `dm_validation` retry params (`GPT5_INCLUDE_LEGACY_TEMPERATURE = False`).
- The resolved `model` value is exactly `gpt-5.6-luna` for all task IDs, confirming `get_model_config()` resolves Luna through the active `model_config.py` assignments.

## 2. Retry Escalation Behavior

- `_resolve_gpt5_chat_profile()` (utils/ai_client_factory.py lines 57-64) escalates only `reasoning_effort` to `"high"` when `retry_tier in {"high", "retry"}`; `verbosity` stays at the task's base profile value (low for validation, medium for combat main).
- The retry guard honors `GPT5_USE_HIGH_REASONING_ON_RETRY` from `model_config.py`; the direct `retry_tier="high"` call also escalates regardless (retry_tier takes precedence by design).
- `core/managers/combat_manager.py` line 4888 passes `retry_tier="high"` into the combat retry path, confirming the configured high-reasoning retry is exercised in the real call site.

## 3. No Task Profile Changed

- `git diff --name-only -- utils/ai_client_factory.py` -> empty (0 files). The shim file is unmodified in the worktree; `_resolve_gpt5_chat_profile()` retains its pre-swap profile table (validation/action_prediction/updates = low/low, compression = low/low, summary/chronicle/diary = low/medium, default = medium/medium, retry escalation = high).
- `model_config.py` worktree diff is model-ID-only (task 1.2 swap of `gpt-5.4-mini-2026-03-17` -> `gpt-5.6-luna`); no profile, retry-policy, or flag lines were changed.
- `GPT5_USE_HIGH_REASONING_ON_RETRY = True` (model_config.py line 46) remains enabled:

```bash
.venv/bin/python -c "from model_config import GPT5_USE_HIGH_REASONING_ON_RETRY; assert GPT5_USE_HIGH_REASONING_ON_RETRY is True; print(...)"
```

Result: `PASS: GPT5_USE_HIGH_REASONING_ON_RETRY = True`

## 4. Conclusion

Task 2.2 verified: `gpt-5.6-luna` resolves medium/medium for narrator (`dm_main`) and combat (`combat_main`), the existing low/low profiles for validation (`dm_validation`), action prediction (`action_prediction`), and compression (`narrative_compression`), high reasoning on configured retry escalation with base verbosity preserved, legacy sampling omitted by default, and no task profile or retry flag was changed. All checks were provider-free; no runtime code was modified.
