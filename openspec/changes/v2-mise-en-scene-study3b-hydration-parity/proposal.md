# Proposal

## Why

The Study 3 adjudication found that accepted request-public fact IDs were not all materialized by the reused Study 2 hydration path, so the final corrected run needs end-to-end parity rather than another interpretation of the prior result. This change defines the separately authorized, isolated Study 3b preparation and bounded rerun while keeping all Study 1/2/3 source and evidence immutable.

## What Changes

- MUST add Study 3b-only request/contract/hydration parity, driven by a canonical per-scene fact inventory and provider-free mutation tests; guarded content and protected unknowns remain protected and are never inferred or promoted.
- MUST adjudicate, offline, whether the actual ha003 request marks guarded content as guarded; diagnostics may report only a stable status, hashes, and necessary fact IDs, never request or output prose.
- MUST use study ID `mise-en-scene-study3b-20261111`, an independent run root, append-only ledger, and lock identity `llm-staging-study3b-20261111`; preserve the ordered scenes `into_the_deepvault:scene:ha003-i02`, `into_the_deepvault:scene:sd005-i03`, and `xhalruuns_masquerade:scene:tsu001-ao02`.
- MUST enforce OpenRouter `openai/gpt-6-luna`, 16,384 max tokens, a 720-second timeout, at most one attempt per scene and three total, no retry/fallback or availability GET, and a USD 0.05 hard ceiling reconciled against an actual-cost receipt.
- MUST gate primary-only dispatch on approvals pinned to the exact final head and Study 3b protocol/config hashes, all 11 required CI checks green on that head, and a clean provider-free preflight with zero infrastructure failures. Provider outage, quota, timeout, or other transport failure stops dispatch without retry; later attempts remain unspent and recovery requires separate authority.
- MUST keep raw outputs private until independent review and send exactly one metadata-only Overseer handoff. A protocol defect blocks the staging line; Study 4 is not opened.

Scope is planning plus the future isolated Study 3b implementation/run only. MUST NOT modify prior study code, protocols, evidence, reports, or verdicts; perform a provider call, archive, merge, or Study 4 closeout; or expose generated prose. No shared gameplay path changes, so 1-PC and multi-PC runtime behavior is unaffected.

## Capabilities

### New Capabilities

- `tt-mise-en-scene-staging-study`: owns the isolated staging-study contract, including request/contract/hydration parity, guarded-knowledge handling, bounded execution, and privacy-safe handoff.

### Modified Capabilities

None. The new Study 3b boundary is separate; existing Study 3 capability requirements are not changed.

## Impact

The planned implementation and focused tests belong under `scripts/mise_en_scene/llm_staging_study3b/`. It may read the existing Study 3 bindings/request/contract and Study 2 hydration/transport sources as immutable inputs; it must not edit them or write into prior-study roots. Run and preparation records belong only in the new Study 3b roots under `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/`. No gameplay API, dependency, or shared runtime changes are planned.
