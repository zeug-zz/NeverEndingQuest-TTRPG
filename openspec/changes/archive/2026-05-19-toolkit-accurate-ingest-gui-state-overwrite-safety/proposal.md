# Proposal: Accurate-Ingest GUI State And Overwrite Safety

## Problem

The accurate-ingest GUI builder path is now closer to a source-faithful module build, but the operator-facing flow still has two high-risk gaps:

1. GUI status can collapse distinct accurate-ingest phases into generic builder progress, making it hard to know whether the pipeline is extracting source truth, building a blueprint, awaiting review, seeding, enriching, checking fidelity, or finishing publication.
2. Existing-module overwrite safety can be bypassed by helper or retry paths if they call packet build functions directly instead of going through the route-level overwrite confirmation flow.

Together these create a dangerous failure mode: a facilitator can see an incomplete or ambiguous status, retry a build, and accidentally replace an existing module without a fresh confirmation or backup-clean rebuild plan.

## Objective

Make the accurate-ingest GUI path visibly staged and overwrite-safe before any production module rebuild work resumes.

The operator should see one coherent operation from upload through final publication status, and any path that can write module files over an existing module must prove route-level confirmation.

## Proposed Solution

Add a focused stabilization slice for:

1. Canonical accurate-ingest GUI phase names.
2. Compact accurate-ingest status summary in job polling payloads.
3. Explicit overwrite authorization contract for packet builds.
4. Tests proving retry and helper paths cannot silently overwrite modules.

Canonical phase order:

```text
preflight -> extracting_source_truth -> building_blueprint -> awaiting_review -> seeding_module -> enriching_module -> build_fidelity -> readiness -> finishing -> publishability_audit -> terminal
```

This slice should not generate or mutate production module data.

## Non-Goals

- This change does not rebuild `modules/The_Hidden_City_of_Numillian/`.
- This change does not implement enrichment provider orchestration.
- This change does not change source-fidelity scoring.
- This change does not redesign the Module Toolkit UI layout beyond narrow status payload/rendering fixes required by tests.
- This change does not relax mandatory fidelity review approval before module files are written.

## Contract Layer (MUST)

- Accurate-ingest jobs MUST expose canonical phase labels for source extraction, blueprint generation, review, seeding, enrichment, build fidelity, readiness, finishing, and publishability.
- Job polling payloads MUST include compact accurate-ingest summary fields: source counts, blueprint status, seed status, enrichment status, build fidelity status, readiness status, publishability status, and source-fidelity status when available.
- Existing-module packet builds MUST refuse overwrite unless a route-level confirmation token or validated rebuild plan artifact is present.
- Retry-from-packet and direct helper paths MUST NOT overwrite existing module directories without explicit confirmation.
- Confirmed rebuilds MUST use the backup-clean rebuild path and preserve existing rebuild safety behavior.
- Finishing-only retry MUST remain allowed when module artifacts already exist and no destructive rebuild is requested.

## Guidance Layer (SHOULD)

- Prefer status normalization helpers over broad frontend rewrites.
- Keep status payload additions additive and backward compatible.
- Keep overwrite authorization checks in the narrowest module-build boundary that all write paths share.
- Prefer source-contract and route/helper tests before template changes.
- Avoid mutating `modules/**` in this slice.

## Risks

| Risk | Mitigation |
|---|---|
| GUI phase labels drift from backend stages | Define one canonical phase map and test the labels. |
| Existing tests depend on old generic progress strings | Keep old fields and add new normalized fields. |
| Helper-level overwrite guard blocks legitimate rebuild | Permit rebuild only with route-issued confirmation or validated rebuild plan artifact. |
| Finishing-only retry is accidentally blocked | Test finishing retry separately from packet rebuild. |

## Success Criteria

1. Accurate-ingest GUI polling payloads expose canonical stage/status fields.
2. GUI source contracts show those fields are rendered or available for rendering without relying on raw logs.
3. First build into a new module directory succeeds.
4. Existing module build without confirmation is refused before write.
5. Confirmed rebuild uses backup-clean rebuild artifacts and proceeds.
6. Retry-from-packet without confirmation refuses overwrite.
7. Finishing-only retry remains allowed.
8. No production module data is changed.
