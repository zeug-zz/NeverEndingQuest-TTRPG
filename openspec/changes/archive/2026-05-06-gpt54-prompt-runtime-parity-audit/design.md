## Context

The GPT-5-family shim lives in `utils/ai_client_factory.py`. It maps model family behavior into chat completion kwargs, including `reasoning_effort`, `verbosity`, and omission of unsupported `temperature` unless explicitly allowed. This is a central compatibility boundary and should be source-tested.

Narrator and combat code include multiple direct chat completion branches. Some already use `get_chat_completion_params()` with `retry_tier`, while other branches may still construct kwargs manually or use inconsistent timeout handling. GPT 5.4 Mini is more likely to follow contradictory local context than older models, so prompt parity and runtime-injected context must be audited together.

## Contract Layer (MUST)

### GPT-5-Family Parameter Contract

- GPT-5-family model calls MUST use supported chat completion parameters produced by the shared factory/shim.
- GPT-5-family params MUST include expected reasoning and verbosity fields when configured.
- GPT-5-family params MUST NOT include unsupported legacy `temperature` by default.
- Non-GPT-5-family calls MUST preserve existing supported parameter behavior.

### Callsite Consistency

- Narrator and combat LLM call paths MUST use `get_chat_completion_params()` or a documented equivalent shared helper.
- Combat and narrator retry paths MUST either use a higher reasoning retry tier after validation failure or document why they do not.
- High-latency combat and narrator calls MUST keep timeout protection.
- Provider fallback behavior MUST remain centralized through existing factory/error-handling helpers.

### Prompt Runtime Parity

- Compressed and uncompressed narrator prompts MUST agree on same-module movement, `updatePartyTracker`, `transitionLocation`, `requestRoll`, and follower-state authority.
- Compressed and uncompressed combat prompts MUST agree on phase authority, PC/enemy mutation routing, `[ALREADY_APPLIED]` replay rules, and combat exit conditions.
- Runtime-injected prompt context MUST NOT contradict the corresponding static prompt authority contracts.

## Guidance Layer (SHOULD)

### Inventory Format

The audit should produce a small developer-facing table in the change notes or tests documenting each relevant callsite:

- file/function
- task id or model source
- uses `get_chat_completion_params()` yes/no
- timeout yes/no
- retry tier behavior
- fallback behavior
- usage tracking behavior

### Test Style

Prefer source-contract and helper-behavior tests over live provider calls. Tests should inspect helper outputs and source text, not call OpenAI or OpenRouter.

### Prompt Sweep Order

Run prompt parity after the narrator and combat runtime stabilization changes, so the audit locks the final authority model rather than stale wording.

## Rollback

- GPT-5 parameter rollback should be centralized in `get_chat_completion_params()`.
- If a callsite migration creates issues, restore its previous kwargs temporarily but add a TODO/source test exclusion explaining why.
- Prompt wording rollback should preserve source-contract tests for known hard failures unless the test itself is proven too broad.
