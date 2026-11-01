# LLM Router Remaining Callsite Migration

## Why

After the facade and core migrations, a fresh production-source inventory still finds chat operations using caller-owned provider transports across generators, memory, validation, utilities, updates, and web/toolkit flows. G6 completes the chat-only migration and adds an enforceable boundary before later provider activation, without changing model selection or invoking a live provider.

## What Changes

- **MUST** migrate every active production chat operation in the source-checked inventory in `design.md` to `llm.call()` with an explicit task key; preserve exact prompt/message bytes, parsing, return behavior, local retry/fallback policy, and applicable legacy usage/log effects.
- **MUST** keep `LLM_PROVIDER = "openai"` and the configured direct model `gpt-6-luna`; this is a transport migration, not a model or provider rollout.
- **MUST** use the existing facade/factory parameter policy for `gpt-6-luna`; do not reintroduce legacy raw `temperature` or `top_p` kwargs that the approved reasoning-family policy omits.
- **MUST** include ordinary action prediction and text-chat operations that produce prompts for image generation. Image, audio, and other media transport remains outside this migration.
- **MUST** preserve provider-free injected seams for toolkit adaptation author/auditor/convergence paths; tests must not require a live client or network access.
- **MUST** add a provider-free production-wide contract/tripwire that detects raw production chat transport outside the documented router and recovery infrastructure.
- **MUST** remove the unreferenced `core/validation/character_validator_backup.py` rather than migrate its dead call sites, after a fresh reference check.
- **SHOULD** use the existing receipt adapter for legacy tracking/logging where applicable, without adding accounting events to operations that did not previously emit them.

## Scope and Non-Goals

- The scope is production chat only, including mixed-purpose modules when their operation is chat. Calls to image, speech/audio, or other media APIs are excluded even when located beside an included chat operation.
- **MUST NOT** activate OpenRouter, remove deprecated router/factory shims, or perform phase-8 cleanup beyond deleting the confirmed-unused validator backup above.
- **MUST NOT** implement Jev decisions, add a Titan runtime/scheduler, remove mode or party-size flags, change gameplay/state ownership, rewrite prompts, or alter image/audio transport.
- G6 verification is provider-free. It does not require or claim a live Capture_Arena verdict.

## Capabilities

### New Capabilities

- `production-chat-facade-only`: Defines facade-only production chat routing and caller-visible behavior parity across the remaining operations.
- `production-chat-tripwire`: Defines the fresh inventory and provider-free guard that prevents production chat transport bypasses.
- `production-chat-accounting`: Defines exactly-once receipt integration with existing usage and API-log consumers for migrated operations.

### Modified Capabilities

- None. Existing router and provider-agnostic usage contracts remain authoritative; these deltas define the remaining-callsite migration boundary.

## Impact

- Affected production areas: `core/generators/`, `core/ai/`, `core/managers/`, `core/memory/`, `core/validation/`, `utils/`, `web/`, `updates/`, and `scripts/run_critical_narrative_repair.py`; focused provider-free tests and the new tripwire are added or updated.
- Both the 1-PC regression floor and multi-PC runtime remain supported. No gameplay mechanics or persisted state contracts change.
- Quota/billing outcomes remain terminal under the facade's existing policy. Existing bounded recovery/fallback behavior remains owned by the facade or the specific caller policy; no new retry layer is introduced.
- No dependency or configuration change is required. Rollback is a revert of the migration and its contract tests; `LLM_PROVIDER` remains `"openai"` throughout.
