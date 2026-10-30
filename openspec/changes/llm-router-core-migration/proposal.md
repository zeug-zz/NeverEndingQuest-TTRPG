# LLM Router Core Migration

## Why

The router facade is implemented and verified, and combat decomposition has established the named combat stages, but the scoped production paths still issue chat through caller-owned clients, timeouts, retries, fallback branches, and usage tracking. This change moves the reinventoried core chat operations behind `llm.call()` while preserving prompt, parsing, action, return, and callback contracts and supplying the primary-owned G4 evidence needed before later rollout phases.

## What Changes

- MUST migrate the exact production chat operations inventoried in `reports/core-chat-inventory.md`: `main.py`, named `core/combat/` stages including direct-AI initiative tracker, and three `core/ai/action_handler.py` operations. Each call uses an explicit legacy task ID; factory/facade owns model and timeout policy.
- MUST preserve prompt bytes/messages, response parsing and control flow, output/return contracts, callbacks, existing semantic retry budgets, fallback notification timing, and model-choice behavior. `get_ai_response()` keeps its prediction boolean and simple/full selection, and continues forcing full choice for validation retry and module creation; direct OpenAI remains selected.
- MUST preserve ordinary main-response empty-completion recovery with at most three empty responses per provider, one fallback transition, and at most six SDK invocations total; use the existing classifier and stop on transport-terminal, refusal/filter, or quota outcomes. Recovery is optional/default-off, forbidden with facade JSON retry, and must not nest the old raw-SDK helper.
- MUST add an optional per-call router observer and a runtime adapter for legacy response/cost/log tracking. It records one event per actual SDK attempt, isolates ordinary observer failures, avoids duplicate manual tracking, and does not change the returned response or stats.
- MUST extend the existing Capture_Arena rig only with fixed `--gate g3` (default) and `--gate g4` support and the four required G4 capture keys. Preserve existing G3 defaults/raw compatibility and standalone latency/G5 scripts.
- MUST keep the scope limited to core routing parity, core runtime usage/recovery, and G4 tooling/capture contracts. All implementation tasks begin unchecked; primary-owned live gate verdicts are not builder claims.

## Capabilities

### New Capabilities

- `core-routing-parity`: Defines routing, task/model policy, timeout ownership, retry/error behavior, and legacy caller-contract parity for the inventoried core chat operations. This is the migration's central production contract.
- `core-runtime-usage-recovery`: Defines receipt-based usage observation, existing tracker/log integration, session reset/notification behavior, and bounded ordinary-main empty-response recovery without double counting.
- `core-live-verification`: Defines bounded G4 Capture_Arena tooling and primary-owned evidence for the core narrator/combat paths. It is necessary because the existing rig is G3-only and G4 requires new named captures before live verification.

### Modified Capabilities

- None. Existing general provider-recovery and usage-tracking specs remain unchanged; this change defines the narrower facade-migration integration contract.

## Impact

- Planned implementation targets: `utils/llm_router.py` and its fake-transport tests; `main.py`; `core/combat/` named stages and `initiative_tracker_ai.py`; `core/ai/action_handler.py`; minimal runtime usage/log adapter; existing Capture_Arena scripts, fixtures, and focused tests.
- Scope excludes `utils/compression/` transport/performance work (G5), `utils/action_predictor.py` chat transport (G6), other generators/utilities (G6), media SDK calls, Jev, new Titan runtime, optional resolver/mode flags, and publication/git work.
- Compatibility: both one-PC and multi-PC tabletop paths remain supported. Prompt/message bytes, mechanics, parsed outputs, public callbacks, and caller-visible return types remain unchanged.
- Provider posture: `LLM_PROVIDER` remains `openai`; normal G4 captures must observe direct OpenAI and no unexpected fallback. Quota/billing errors remain terminal and must not fan out through outer retries; recovery uses the existing router error classifier and bounded fallback policy. Controlled failure tests verify retry, quota, and once-only notification without provider access.
- Runtime usage preserves reported zero cost, labels estimates as estimated, and reports missing cost as unpriced; router-local stats remain a separate programmatic view and are not added to legacy usage/Debug/session/week totals. No router-backed `/usage` UI is in scope. Reset router and fallback session state once per CLI/web runtime launch, not per campaign, game-loop re-entry, turn, restore, or resume; never reset the rolling-week ledger.
