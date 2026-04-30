# Context

`model_config.py` currently points the OpenAI model constants at `gpt-5.4-mini-2026-03-17`, while much of the runtime still uses legacy Chat Completions call-site parameters from the GPT-4.1 era. Many call sites pass `temperature`; a smaller number pass `top_p`. The future router plan already calls for provider/model profiles, but that larger migration is intentionally post-gametest.

# Goals

- Provide a minimal central parameter shim for current GPT-5.4-mini gametesting.
- Keep the shim compatible with the future `llm.call()` / model-profile router direction.
- Avoid broad call-site churn.
- Make GPT-5-style calls omit legacy `temperature` and `top_p` by default.
- Preserve legacy parameters for non-GPT-5 models.

# Non-Goals

- No Responses API migration.
- No full router implementation.
- No model selection strategy rewrite.
- No automatic rewrite of all direct `client.chat.completions.create(...)` calls.
- No prompt semantics change.

# Decisions

## D1. Central Chat Parameter Helper

Add a helper in `utils/ai_client_factory.py` with a narrow contract, for example:

```python
def get_chat_completion_params(
    task_id: str,
    original_openai_model: Optional[str] = None,
    *,
    retry_tier: Optional[str] = None,
) -> Dict[str, Any]:
    """Return model-family-aware parameters for chat.completions.create."""
```

The exact function name may be adjusted by the builder, but the helper must return a flat dictionary intended to be spread directly into `client.chat.completions.create(...)`.

## D2. GPT-5-Style Parameter Policy

For models whose names start with `gpt-5`, the helper must default to:

```python
{
    "model": model,
    "reasoning_effort": task_effort,
    "verbosity": task_verbosity,
}
```

It must not include `temperature` or `top_p` by default for GPT-5-style models.

## D3. Legacy Model Preservation

For non-GPT-5 models, the helper must preserve existing `TASK_TEMPERATURES` behavior and avoid adding GPT-5-only fields.

## D4. Rollback Flag

Add a compatibility flag, default false:

```python
GPT5_INCLUDE_LEGACY_TEMPERATURE = False
```

When true, the helper may include legacy `temperature` for GPT-5-style models as an emergency compatibility fallback. It should not include `top_p` unless separately and explicitly scoped later.

## D5. Limited Adoption

Adoption should be limited to high-value paths after review:
- `main.py` narrator and validation calls.
- `core/managers/combat_manager.py` combat main and validation calls.
- `core/ai/action_handler.py` local helper calls.
- Existing `get_model_config()` users where the patch is local and low-risk.

Direct low-traffic or brittle call sites can remain unchanged until the v2 router migration.

# Suggested Task Profiles

These are guidance, not immutable runtime truth:

| Task Family | reasoning_effort | verbosity |
| --- | --- | --- |
| `dm_main`, `combat_main`, `builders` | `medium` | `medium` |
| `dm_validation`, `validation`, mechanics, structured updates | `low` | `low` |
| `action_prediction` | `low` | `low` |
| `compression`, summaries, diary | `low` | `medium` |
| retry after validation/provider failure | `high` if explicitly requested | unchanged or `low` for strict JSON |

# Hard Constraints

- The helper MUST be additive and must not remove `get_model_config()`.
- GPT-5-style helper output MUST omit `temperature` and `top_p` by default.
- Non-GPT-5 helper output MUST preserve legacy temperature behavior.
- The change MUST NOT migrate to the Responses API.
- The change MUST NOT implement the v2 router.
- The change MUST keep OpenRouter behavior unchanged unless the existing code path already routes through the touched helper.
- Tests MUST cover GPT-5 and non-GPT-5 output behavior.

# Guidance

- Prefer a small profile dictionary in `model_config.py` or `ai_client_factory.py` over scattering per-call constants.
- Prefer source-contract tests for adoption scope instead of broad live provider tests.
- Keep helper output simple and flat to make future router migration easy.
- If SDK support for `reasoning_effort`/`verbosity` is uncertain in a local environment, gate live use behind profile flags rather than spreading try/except blocks across call sites.

# Migration and Rollback

Implementation should proceed in two separable passes:

1. Add the helper, profile mapping, and tests.
2. Adopt the helper in a small set of high-value paths.

Rollback options:
- Disable GPT-5-style fields centrally.
- Enable legacy temperature fallback centrally.
- Revert individual call-site adoption patches without removing the helper.

# Verification Plan

- Compile touched Python files.
- Add tests verifying helper output for GPT-5-style and non-GPT-5 models.
- Add source-contract tests verifying no `top_p` is emitted for GPT-5-style helper output.
- Add source-contract checks for limited adoption targets if call-site patches are implemented.
- Run targeted runtime regression suites for narrator/combat call-site changes if adopted.
