## Why

The direct OpenAI runtime currently uses `gpt-5.4-mini-2026-03-17` across the configured narrator, combat, validation, builder, update, and compression model roles. GPT-5.6 Luna is now the preferred direct-OpenAI model, and its medium reasoning effort is intended to provide a better speed/quality balance for live tabletop play.

This change gives the model replacement an explicit, testable rollout boundary instead of treating it as an unverified string edit. The existing GPT-5-family Chat Completions shim should remain the compatibility layer for reasoning and verbosity parameters.

## What Changes

- Replace active direct-OpenAI GPT-5.4 Mini model constants with the exact model ID `gpt-5.6-luna`.
- Update the legacy GPT-5 selector constants so alternate GPT-5 runtime branches cannot silently fall back to GPT-5.4 Mini.
- Preserve the existing GPT-5-family parameter shim and task profiles, including medium effort for narrator/combat, low effort for validation/compression, and high-effort retries where configured.
- Add human-readable model display-name coverage for GPT-5.6 Luna.
- Update current model-contract tests and source references so they validate Luna behavior without changing the generic GPT-5-family shim contract.
- Audit the existing direct-OpenAI call paths that still pass legacy sampling parameters and document or minimally correct any path that prevents Luna operation.
- Verify the swap with provider-free tests plus an explicitly documented direct-OpenAI smoke test.

The following are explicitly out of scope:

- OpenRouter model selection or OpenRouter-specific parameter behavior.
- Responses API migration.
- The planned provider-agnostic `llm.call()` router.
- Prompt, gameplay, routing-policy, retry-count, or timeout changes unless required to keep the existing Luna call contract valid.
- Performance guarantees; observed tokens per second remain provider/runtime measurements, not a repository contract.

## Capabilities

### New Capabilities

- `gpt56-luna-direct-openai-runtime`: Direct-OpenAI GPT-5.6 Luna model selection, GPT-5-family parameter compatibility, display identity, and rollout verification.

### Modified Capabilities

None. The existing GPT-5-family shim contract remains generic and is reused rather than changed.

## Impact

- `model_config.py`: direct-OpenAI model assignments and related model comments.
- `utils/ai_client_factory.py`: model display-name mapping and, only if needed, narrow compatibility handling discovered during the audit.
- Existing GPT-5 contract tests and any focused runtime regression tests.
- Direct OpenAI Chat Completions calls using these model constants; all existing provider fallback behavior remains unchanged.
- No database, schema, saved-game, module-artifact, or gameplay-state migration is required.
- Both single-player and TABLETOP MODE remain on the same model configuration path; a server restart is required to load the new model values.
