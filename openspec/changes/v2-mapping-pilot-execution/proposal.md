# Proposal

## Why

The SP1 tooling and SP2 offline artifacts exist, but the preregistered SP3 matrix still lacks thin end-to-end orchestration and SP4 lacks a reproducible owner-review and decision-gate handoff. This change closes those phases without changing the frozen preregistration or production gameplay.

## What Changes

### Contract Layer (MUST)

- MUST add only the missing provider-free-testable matrix runner and review/report glue under `scripts/mapping_pilot/`, reusing the seeder, launcher, adapter, socket driver, zone ledger, scoring, evidence, D1, and M1 tooling.
- MUST run the exact 30-slot counterbalance only; enforce the frozen attempt and wall-time caps before requests, preserve resumable row evidence, classify reserve eligibility before content review, and pause after three consecutive infrastructure failures.
- MUST gate all SP3 live work on a booked port-8360 window with the Overseer, record booking and release, and prevent overlap with Network live runs. Only the primary orchestrator runs live rows.
- MUST generate partially blinded live-transcript review packets and an SP4 report covering Q1-Q6 and the five preregistered recommendations; owner ratings, the D1 audit, the Module Builder requirements/gap handoff, and the gate record remain human/orchestrator inputs and MUST NOT be fabricated.
- MUST record Stage 1 ratings as waived, not as scores, and draft (not accept) the spatial-authority/projections ADR for explicit owner decision.
- MUST preserve arm A as a no-op and avoid production defaults, core hooks, `model_config.py`, `modules/`, installed campaign, web/client, and port-8357 changes.

### Guidance Layer (SHOULD)

- SHOULD preserve exact counterbalance, script, fixture, rubric, threshold, and budget bytes by validating and reading the frozen preregistration rather than copying or regenerating it.
- SHOULD keep provider-free tests isolated with injected process, socket, and router boundaries; use project-relative `tmp/` for run evidence.

## Non-Goals

- No edits to the preregistration fixtures, scripts, `counterbalance.json`, rubric, thresholds, matrix, budgets, or stop rules.
- No live row, provider call, server start, owner rating, D1 audit, ADR acceptance, or gate verdict during planning or builder verification.
- No change to the completed `v2-mapping-pilot-tooling` or `v2-mapping-pilot-offline` changes beyond reusing their published interfaces and evidence.

## Capabilities

### New Capabilities

- `mapping-pilot-execution`: Specifies booked, bounded SP3 matrix execution and evidence plus the SP4 blinded review, adjudication, and owner decision-gate handoff.

### Modified Capabilities

None.

## Impact

Implementation is limited to missing developer tooling and provider-free tests under `scripts/mapping_pilot/` and `scripts/`, the new OpenSpec change, and SP4's proposed ADR/index entry under `adrs/`. Live artifacts remain under project-relative `tmp/router-rollout/mapping-pilot/`; the existing Capture Arena sandbox stays under `tmp/combat_capture/`. No production API, model route, or runtime behavior changes.
