# Why

The current gametest build has swapped the primary OpenAI model constants in `model_config.py` from GPT-4.1-family models to `gpt-5.4-mini-2026-03-17`. Early gameplay testing shows better speed and intelligence in narration, combat, and module-builder flows, but many legacy Chat Completions call sites still pass GPT-4-era sampling parameters such as `temperature` and sometimes `top_p`.

The future v2 direction is still the provider/model-agnostic router described in `plans/version-2/openrouter_llm_router_architecture.md`. This change is intentionally a short-term gametest shim: it improves GPT-5.4-mini parameter hygiene without migrating to the Responses API, replacing the router plan, or touching every LLM call site.

# What Changes

- Add a small central helper in `utils/ai_client_factory.py` that builds Chat Completions parameter dictionaries by task and model family.
- For GPT-5-style OpenAI models, omit legacy sampling controls by default and use GPT-5-style `reasoning_effort` and `verbosity` task profiles.
- For non-GPT-5 models, preserve existing legacy `temperature` behavior.
- Add an explicit rollback compatibility flag, default false, for including legacy temperature with GPT-5-style models only if this specific API route unexpectedly requires it.
- Apply the helper only to a small set of high-value gametest call sites after review.
- Add source-contract tests for helper behavior and limited adoption scope.

# Capability Scope

This change covers Chat Completions parameter construction and limited high-value adoption only.

In scope:
- `utils/ai_client_factory.py` helper and task-profile mapping.
- `model_config.py` feature flags/profile constants if needed.
- Limited call-site adoption for narrator, combat, action helper, and already-factory-mediated paths.
- Tests that assert GPT-5-style calls omit `temperature` and `top_p` by default.

Out of scope:
- Responses API migration.
- Full `llm.call()` router implementation.
- OpenRouter strategy rewrite.
- Broad migration of all 80+ raw Chat Completions call sites.
- Provider/model selection changes.
- Behavioral prompt changes.

# Non-Goals

- Do not make GPT-5.4-mini the long-term architecture boundary.
- Do not create a competing router beside the planned v2 model-profile router.
- Do not alter image, TTS, embeddings, or non-chat provider paths.
- Do not require all existing tests to be updated for every legacy call site.

# Impact

Expected benefits:
- Cleaner GPT-5.4-mini behavior for the hottest gametest paths.
- Lower risk of future API rejection from legacy `temperature`/`top_p` parameters.
- Easier rollback than a broad call-site migration.
- Better alignment with the eventual model-profile architecture.

Expected implementation size:
- Small central helper and profile mapping.
- A handful of source-contract tests.
- Optional adoption in 4-8 high-value call sites.

# Risks

- Chat Completions support for GPT-5-style fields may vary by model or SDK version.
- Some direct call sites will continue using legacy parameters until the future router migration.
- Over-aggressive call-site adoption could destabilize combat/narration before gametesting.

# Fallback

- Keep a single rollback flag such as `GPT5_INCLUDE_LEGACY_TEMPERATURE = False`.
- If a live smoke shows GPT-5-style Chat Completions rejects `reasoning_effort` or `verbosity`, disable those fields in the helper or narrow adoption without reverting unrelated model constants.
- If a call site regresses, revert only that call-site adoption and leave the helper/tests intact for later use.

# Merge Safety and SP/MP Impact

- This is not a TABLETOP MODE behavior fork; the helper should be safe for both SP and MP because it only changes API parameter construction where adopted.
- The change should be clearly isolated in `utils/ai_client_factory.py` and guarded by model-family detection.
- Existing non-GPT-5 OpenAI model behavior must remain unchanged.
