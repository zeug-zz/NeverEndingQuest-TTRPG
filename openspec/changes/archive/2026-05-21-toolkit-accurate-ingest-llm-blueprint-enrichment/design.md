# Design: LLM Blueprint Enrichment

## Overview

This change implements the first real provider-backed blueprint enrichment passes while preserving Python authority over source locks, IDs, connectivity, schema structure, and patch application. The enrichment layer proposes field-level prose/source-context patches; Python validates and applies only allowed patches.

The implementation MUST proceed incrementally. The first runtime slice is NPC enrichment only. Later slices add location, plot/puzzle/clue, encounter/item, tone, and telemetry behavior.

## Architecture Boundary

The existing ModuleBuilder orchestration remains the creative authoring path. Enrichment prepares a richer source-faithful blueprint for later handoff; it does not materialize a complete module and does not replace ModuleBuilder.

The deterministic seed writer remains support/fallback tooling and SHALL NOT become the default GUI authoring path in this change.

## Enrichment Pipeline

The pipeline should keep the existing status contract:

```text
disabled -> skipped
provider unavailable/no-op -> not_implemented or degraded
provider/parse/pass errors -> degraded or failed
valid patches applied with no errors/rejections -> complete
```

Each pass should:

1. Select bounded source excerpts relevant to a pass target.
2. Build a pass-specific JSON-output prompt.
3. Call the configured chat provider only when enrichment is enabled.
4. Parse JSON strictly.
5. Convert proposed field updates into enrichment patches.
6. Validate patches with existing structural mutation guards.
7. Apply only accepted patches.
8. Record pass diagnostics, source refs, provider metadata, and cache/telemetry fields.

## NPC Pass First

The NPC pass is the first implementation target because Numillian exposes both failure classes:

- `but this is not true` is a narrative assertion and must remain rejected/reclassified as non-actor text.
- Dog-Growl, Book-shut, and Deflation are valid Kenku residents and should gain location binding to The Rookery plus role/context/source refs.

The pass MUST consume existing candidate triage output when present. It MAY enrich kept NPCs and MAY preserve non-actor rejected candidates as diagnostics, plot notes, or tone markers, but it MUST NOT promote rejected narrative phrases into actor records.

## JSON Contract

Provider output should be a compact JSON object containing pass metadata and proposed patches. The implementation may evolve exact field names, but it MUST include enough information to validate:

- pass name and target type
- proposed patches
- source refs or source-derived justifications
- candidate/entity identity references
- warnings or confidence diagnostics

Invalid JSON, schema drift, missing required source refs, or unsafe patch targets degrade the pass and must not corrupt artifacts.

## Source Refs And Patch Safety

All applied patches MUST include source refs or a source-derived justification. The patch validator remains authoritative over allowed fields. Structural fields remain forbidden: names, IDs, coordinates, connectivity, dependencies, puzzle rules, puzzle solutions, failure consequences, and replacement main plotlines.

## Caching And Telemetry

The first pass SHOULD use deterministic input hashing for source excerpts and target identity. Cache misses may call the provider when enabled; cache hits should avoid provider calls. Telemetry should identify pass names, provider call count, cache hit/miss count, parse failures, rejected patch count, and applied patch count.

Cache/telemetry must be additive and fail-open. Missing cache data must not block enrichment.

## Provider Failure Semantics

Provider failures are expected operational conditions. Timeout, quota, API errors, parse errors, and validation failures MUST return degraded or failed diagnostics without mutating unrelated blueprint/module artifacts. Tests MUST be able to simulate these paths without live provider credentials.

## Rollback

If enrichment causes regressions, disable `ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT`. Existing default-off behavior and ModuleBuilder routing remain intact. The change should not require data migration to roll back.
