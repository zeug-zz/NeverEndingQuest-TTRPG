## Context

The current direct-OpenAI configuration assigns `gpt-5.4-mini-2026-03-17` to the primary GPT-5 runtime roles. `config.py` imports these values from `model_config.py`, so a model assignment change is loaded at process startup without changing persisted game state.

The shared helper in `utils/ai_client_factory.py` identifies GPT-5-family models by the `gpt-5` prefix. It supplies task-aware `reasoning_effort` and `verbosity` values and omits legacy sampling parameters by default. The helper is already used by the main narrator, combat, and selected action-handler paths, while some lower-traffic call sites still use older direct parameter construction.

The repository's configured target for this change is direct OpenAI only. OpenRouter model selection and its separate `thinking` parameter path remain untouched.

## Goals / Non-Goals

**Goals:**

- Make `gpt-5.6-luna` the active direct-OpenAI GPT-5 model for the existing configured roles.
- Preserve the existing GPT-5-family parameter policy and effort profiles.
- Ensure alternate GPT-5 selector branches cannot silently select GPT-5.4 Mini.
- Keep model display, model-selection logging, and provider-free contract tests aligned.
- Audit high-value and reachable direct-OpenAI call paths for incompatible legacy sampling arguments.
- Provide a reversible rollout with explicit live-smoke verification.

**Non-Goals:**

- Do not create a new router or model abstraction.
- Do not migrate calls from Chat Completions to the Responses API.
- Do not change prompts, intelligent-routing decisions, retry counts, timeouts, or gameplay semantics.
- Do not modify OpenRouter behavior, model IDs, or OpenRouter-specific request fields.
- Do not promise a particular tokens-per-second rate.
- Do not add persistent data migration or campaign-state changes.

## Decisions

### Use the unversioned direct-OpenAI model ID

The active model value will be `gpt-5.6-luna`, not an OpenRouter-prefixed identifier and not an invented date-suffixed snapshot. The direct OpenAI client receives the model string unchanged.

**Alternative considered:** Use `openai/gpt-5.6-luna`. Rejected for this change because the repository's selected provider is direct OpenAI; provider-prefixed IDs belong to the separate OpenRouter path.

### Reuse GPT-5-family detection instead of adding a Luna branch

The existing `startswith("gpt-5")` detection already covers Luna. The implementation MUST NOT add a model-specific conditional for Luna unless a live API incompatibility proves that the generic contract is insufficient.

This keeps the shim capability-based and preserves the planned future router boundary.

### Preserve the existing effort profile

The current task profiles remain authoritative:

- Main narration and combat use medium reasoning and medium verbosity.
- Validation, action prediction, updates, and compression use low reasoning and low verbosity where currently configured.
- Validation retries use high reasoning where the existing retry policy requests it.

The phrase "Luna medium" therefore maps to the request parameter `reasoning_effort="medium"`; it is not encoded in the model ID.

### Replace active model assignments, not historical artifacts

All active `gpt-5.4-mini-2026-03-17` assignments in `model_config.py` that select the runtime GPT-5 model will be changed, including `GPT5_MINI_MODEL` and `GPT5_FULL_MODEL`. Historical OpenSpec archives may continue to describe the prior GPT-5.4 change.

Current contract tests and display metadata will be updated because they describe active behavior. No broad rewrite of every legacy direct call site is planned; only call sites that block the targeted direct-OpenAI runtime are corrected.

### Keep failure and rollback behavior explicit

An unavailable or rejected Luna request MUST remain visible through the existing error/retry path and MUST NOT silently revert to GPT-5.4 Mini. Rollback is performed by restoring the previous model assignments and restarting the server.

No new mutable shared state is introduced. Existing provider fallback bookkeeping remains unchanged and is not treated as a Luna fallback mechanism.

## Risks / Trade-offs

- **[Risk] The account or endpoint does not expose `gpt-5.6-luna`.** -> Run a direct-OpenAI smoke request before gameplay testing; report the provider error and roll back the model assignments without changing fallback semantics.
- **[Risk] A lower-traffic call site still sends an unsupported legacy sampling field.** -> Inventory direct model calls, run focused provider-free checks, and minimally route only blocking calls through the shared helper.
- **[Risk] Medium effort is slower or faster than expected.** -> Treat latency and output rate as measured smoke-test telemetry, not as a correctness gate or hard-coded behavior.
- **[Risk] A process continues using cached configuration after the edit.** -> Require a clean server restart in the rollout checklist and verify the selected model in existing model-selection logs.
- **[Risk] Display or tests retain stale GPT-5.4 assumptions.** -> Update active display mappings and contract fixtures while leaving historical archive documentation unchanged.
- **[Risk] Direct OpenAI behavior is accidentally changed for OpenRouter.** -> Keep provider-specific branches unchanged and add a source/contract assertion that this change does not modify `OPENROUTER_CHAT_MODEL` or OpenRouter request fields.

## Migration Plan

1. Capture the baseline targeted test results and current model-selection behavior.
2. Replace active direct-OpenAI GPT-5 assignments with `gpt-5.6-luna`.
3. Update display metadata and current GPT-5 contract fixtures.
4. Audit and minimally correct any blocking direct call sites while preserving the existing helper boundary.
5. Run syntax, provider-free contract, and targeted regression tests.
6. With direct OpenAI credentials available, run one bounded narrator request and one combat request, recording selected model, request-parameter acceptance, latency, and output validity.
7. Restart the normal server and perform a short single-player and TABLETOP MODE smoke check.

Rollback consists of restoring `gpt-5.4-mini-2026-03-17` in the active model assignments, restarting the server, and retaining the compatibility/test changes that remain valid for the GPT-5 family.
