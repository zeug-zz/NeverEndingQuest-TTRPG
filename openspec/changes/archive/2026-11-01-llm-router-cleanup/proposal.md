# Proposal

## Why

The router owns production chat selection and response-derived cost provenance, but the legacy usage rollups and Debug panel do not yet present a reconciled session/week view, and no `/usage` command exposes the router snapshot. Build 8 completes the approved G10 rollout after G9, removes only verified-retired router selection residue, and proves save/resume behavior in both supported party shapes.

## What Changes

### Contract Layer (MUST)

- MUST add a read-only `/usage` command and reconcile router chat receipts with session/week chat cost rollups using actual, verified-estimated, or unpriced provenance; an unpriced call MUST remain visible as incomplete and MUST NOT be reported as free or counted twice.
- MUST preserve cost-only media events and their existing token-count behavior while adding chat provenance to the existing Debug session/week rollups.
- MUST remove only the selection constants/helpers, alias, stale imports, and migration tooling whose current references are audited in `design.md`; retain factory transport, actual-provider detection, parameter finalization, and fallback notification ownership.
- MUST leave the installed `LLM_PROVIDER` default unchanged; activation owns that default. Provider quota/billing failures and the existing bounded recovery behavior remain unchanged.
- MUST preserve the G1/G3/G4/G5R goldens and all nine legacy combat prompt hashes byte-for-byte, and preserve 1-PC and 4-PC gameplay/save-resume behavior.
- MUST require a recorded primary-owned G9 PASS in `llm-router-openrouter-activation` before any cleanup implementation task begins.
- MUST define G10 as a primary-owned Capture_Arena gate covering one bounded full session per 1-PC and 4-PC party, including narration, combat, save, restart/resume, `/usage`, and Debug session/week cost-provenance observations. Each run MUST retain expected/observed evidence under `tmp/router-rollout/g10/<run-id>/`.
- MUST sync durable documentation for the resulting ownership and accounting behavior.

### Guidance Layer (SHOULD)

- SHOULD extend the existing router receipt observer, provider-agnostic usage tracker, Debug `token_update`, and Capture_Arena path rather than creating a parallel ledger, command framework, or capture driver.
- SHOULD keep provider-free implementation tests and G10 evidence evaluation separate from the primary's live verdict.

## Scope and Non-Goals

- This change covers router cleanup, `/usage`, chat cost reconciliation, Debug rollups, durable documentation, and G10 evidence/tooling needed for the specified live gate.
- MUST NOT cut over image or audio providers, implement Jev, add a Titan runtime, or remove `MULTIPLAYER_MODE` or party-size gates.
- MUST NOT change gameplay mechanics, prompt bytes, installed provider defaults, media transport, or the primary-owned G10 verdict.
- `core/validation/character_validator_backup.py` was already deleted by G6 and is not a Build 8 removal.

## Capabilities

### New Capabilities

- `llm-router-g10-verification`: Defines the fixed G10 full-session evidence contract and primary ownership of the live verdict.

### Modified Capabilities

- `provider-agnostic-usage-tracking`: Defines `/usage` and reconciled session/week chat totals with actual, estimated, and unpriced provenance while preserving cost-only media events.
- `debug-tab-usage-cost-rollup`: Defines additive Debug rollup fields for provenance and cost completeness without changing legacy token display behavior.

## Impact

- Expected implementation areas include `utils/llm_router.py`, `utils/llm_runtime.py`, `utils/llm_usage_tracker.py`, `utils/ai_client_factory.py`, `model_config.py`, `main.py`, the Debug token-update path/template, focused provider-free tests, the existing Capture_Arena seeder/driver/evaluator, and durable operational documentation.
- The `/usage` command is read-only and makes no provider request. Existing quota/billing terminal behavior and bounded fallback remain owned by the router/factory.
- Shared session and combat behavior must pass the 1-PC regression floor and 4-PC coverage; G10 live execution and its verdict belong to the primary orchestrator, not the builder.
