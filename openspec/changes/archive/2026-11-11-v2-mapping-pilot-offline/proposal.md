# Proposal

## Why

SP1 supplies reusable cartography and sketch-rendering primitives, but SP2 still needs a reproducible, owner-approved D1 selection and routed live invocation, plus the complete M1 sketch/rating packet. A small follow-up keeps this work separate from the existing tooling change and produces auditable offline evidence for the SP4 owner sitting without changing production gameplay or module data.

## What Changes

### Contract Layer (MUST)

- MUST add a live-client adapter in `scripts/mapping_pilot/` that presents the cartographer's injected client interface while using the existing LLM router and preserving per-call receipts for requested/resolved model, provider, fallback, and usage; unknown receipt fields remain unknown.
- MUST deterministically select 20 D1 locations from `Keep_of_Doom` (7), `The_Thornwood_Watch` (6), and `The_Pumpkin_Kings_Curse` (7), stratifying by authored area type, sorting location IDs within each type, and round-robining across types. Before any provider call, MUST write a selection record containing each location's source path and SHA-256 plus the repository commit.
- MUST require that selection record for the D1 run, enforce the 60-call cap, use the frozen `production-auto` route without pinning a downstream model or changing `model_config.py`, and write D1 outputs only below `tmp/router-rollout/mapping-pilot/d1/<run-id>/`. No output may be written to `modules/`.
- MUST produce M1 sketches for all four preregistered fixtures, their preregistered P1/P4 viewpoints where defined, and validated D1 layouts. MUST produce a separate owner sheet with blank 1-5 legibility and usefulness ratings, under `tmp/router-rollout/mapping-pilot/m1/<run-id>/`.
- MUST include provider-free tests using a fake router/client. The final integrated verification and live D1/M1 evidence run are orchestrator-owned; builders do not run the live pass. D1 audits and M1 ratings remain SP4 owner inputs, not completion tasks beyond producing the review artifacts.

### Guidance Layer (SHOULD)

- SHOULD reuse the existing cartographer extraction, prompt, validation, audit-sheet, M1 rendering, and evidence boundaries rather than introducing parallel mapping abstractions.
- SHOULD retain source/run provenance and receipt data alongside each run's artifacts so SP4 can distinguish offline, provider-free, and live evidence.

## Non-Goals

- No changes to the existing `v2-mapping-pilot-tooling` change, production code, model configuration, published modules, or `modules/` data.
- No owner audit values, D1 precision judgment, or M1 ratings are filled by this change; it produces blank review artifacts for the SP4 sitting. Historical Stage 1 packet ratings remain waived and are not recreated.
- No SP3 transcript rating, spatial decision report, module backfill, archive, or publication work is included.

## Capabilities

### New Capabilities

- `mapping-pilot-offline`: Reproducible D1 source selection and routed execution, plus fixture/D1 M1 sketch and blank owner-rating artifacts for SP2.

### Modified Capabilities

None. Existing production behavior requirements do not change.

## Impact

Implementation is limited to `scripts/mapping_pilot/` and provider-free tests under `scripts/`; run artifacts are limited to the two specified project-relative `tmp/router-rollout/mapping-pilot/` subtrees. No edits are in scope for the existing `v2-mapping-pilot-tooling` change, `modules/`, `core/`, `main.py`, `model_config.py`, `web/`, or clients. The D1 adapter uses the existing router's frozen production-auto policy and fallback behavior; a quota/provider error is retained as a failed call with its receipt, consumes the call budget, and may be resumed only through the same recorded selection while budget remains. No new provider fallback or model pin is introduced. Fixture viewpoints cover the preregistered P1/P4 cases where present; no gameplay party-size behavior changes.
