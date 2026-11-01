# Proposal

## Why

The facade and production chat migrations now route chat through the shared router, but runtime configuration still selects direct OpenAI, so accepted OpenRouter Auto routing has not been activated. Build 7 is the approved activation point; G9 must follow a primary-owned G7 PASS, and the current G7 verdict is BLOCKED by unavailable network access.

## What Changes

- MUST activate chat with `LLM_PROVIDER = "openrouter"` and `ACTIVE_PROFILE = "production-auto"` only after G7 PASS. Keep narrator (`dm_main`), combat (`combat_main`), and Titan (`titan_cycle`) task configuration independent; Titan receives configuration and a fake-transport proof only.
- MUST add explicit per-task sampling policies for every production chat task, covering reasoning and non-reasoning request families. The factory MUST preserve reasoning-family omission of `temperature` and `top_p`, and finalize task-specific sampling for non-reasoning Auto requests; compression retains its established `temperature = 0.3` policy.
- MUST account for requested versus resolved model, actual transport/upstream provider when observable, and reported, verified-estimated, or unpriced cost with completeness. Auto calls without response cost or verified resolved-model rates remain explicitly unpriced; do not merge router totals into session/week UI accounting in this change.
- MUST extend the existing Auto Router `medium` cost tier to every request using task `dm_main` when the request model is exactly `openrouter/auto`, including JSON-contract narrator calls, while retaining medium for configured response validators. Preserve all other task defaults and direct-OpenAI/fallback behavior.
- MUST retain one bounded transport-failure fallback to direct OpenAI `gpt-6-luna` and prove an operator rollback to direct `gpt-6-luna` with one server restart.
- MUST extend the existing Capture_Arena seeder, socket driver, and evidence evaluator with `--gate g9`, provider-free tests, and a primary-owned live G9 matrix for narrator/combat Auto on 1-PC and 4-PC parties, controlled fallback, and rollback. Preserve evidence under `tmp/router-rollout/g9/<run-id>/`; run the real sandbox only under `tmp/combat_capture/` on port 8360.
- MUST preserve Python mechanical authority, prompt bytes and all nine legacy prompt hashes, G1/G3/G4/G5R goldens, DM ownership of `/end`, and 1-PC/4-PC behavior. Keep rollout-only flags off outside the sandbox.
- MUST NOT require another candidate bake-off or approval round. Image/audio cutover, Jev, a new Titan runtime, and mode-flag removal remain excluded.

## Capabilities

### New Capabilities

- `llm-openrouter-runtime-activation`: Defines Auto activation, independent task profiles, task-family sampling, bounded direct-OpenAI fallback, actual-model cost provenance, and preferred-model rollback.
- `llm-openrouter-g9-verification`: Defines the G9 capture-tooling contract, required evidence, G7 prerequisite, and primary ownership of the live verdict.

### Modified Capabilities

- None. The existing facade usage contract remains the source for router-local accounting mechanics; this change defines activation and G9 acceptance without changing the legacy session/week tracker.

## Impact

- Expected implementation areas: `model_config.py`, `utils/ai_client_factory.py`, `utils/llm_router.py`, focused router/factory tests, and the existing `scripts/seed_combat_capture.py`, `scripts/capture_drive.py`, `scripts/capture_evidence.py`, fixture, and capture-test seams.
- Provider quota/billing failures remain terminal. A classified transient transport failure may use the existing one-fallback bound; the fallback and rollback resolve to direct OpenAI `gpt-6-luna` without OpenRouter-only request settings.
- G7 is currently BLOCKED on network availability. G9 live execution cannot start or pass until the primary records G7 PASS. Provider-free tests and tooling do not substitute for G9 live evidence.
