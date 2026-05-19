# Proposal: Accurate-Ingest Seed Writer Completion

## Problem

The accurate-ingest GUI builder unification depends on the deterministic blueprint being the actual build contract for uploaded adventures. The current seed writer can materialize core module files from `builder_blueprint.v2`, but audit found three gaps that prevent it from being the reliable insertion point between source extraction and LLM enrichment:

1. It does not emit `npcs_seed.json` and `monsters_seed.json`, even though media prewarm, monster materialization, MMG authority, and publication workflows consume those artifacts.
2. It can report `seed_status: success` even when required writes are skipped or fail.
3. It does not provide enough source-preservation metadata for later fidelity gates to prove original names, source order, blueprint IDs, and source refs survived deterministic materialization.

These gaps undermine the prime directive of accurate ingest: uploaded adventure structure must be preserved before any LLM builder/enrichment step can invent or polish prose.

## Objective

Complete `utils/toolkit_blueprint_seed_writer.py` so it is a provider-free, source-preserving, failure-honest materializer for accurate-ingest GUI builds.

The seed writer MUST create the canonical module skeleton and supporting seed/report artifacts needed by the rest of the toolkit before LLM enrichment, readiness, media, and publication stages run.

## Proposed Solution

Extend the deterministic seed writer to:

1. Emit `npcs_seed.json` from blueprint `npc_roster`.
2. Emit `monsters_seed.json` from blueprint `encounter_plan`, location monster references, and source monster hints where available.
3. Emit a workspace/module-side seed source report that preserves blueprint IDs, original source names, source order, and source refs when module schemas cannot safely carry that metadata directly.
4. Classify write results by severity and refuse to continue as successful when required canonical files fail.
5. Keep `dry_run=True` provider-free and write-free while reporting every planned artifact.

## Non-Goals

- This change does not implement LLM enrichment.
- This change does not change GUI route state handling or overwrite confirmation policy beyond seed-writer-level refusal semantics.
- This change does not wire source-fidelity into publication audit; that belongs in the next slice.
- This change does not regenerate Numillian production artifacts by itself.
- This change does not remove legacy v1 blueprint or ModuleBuilder concept-first behavior.

## Contract Layer (MUST)

- The seed writer MUST NOT call LLM providers.
- The seed writer MUST preserve source location/NPC names before enrichment starts.
- The seed writer MUST emit NPC and monster seed artifacts for blueprint-native builds.
- The seed writer MUST not report success if required canonical artifacts failed to write.
- Existing `dry_run=True` behavior MUST remain non-mutating.
- Existing blocked/non-v2 blueprint refusal behavior MUST remain fail-closed.

## Guidance Layer (SHOULD)

- Prefer small helper functions in `utils/toolkit_blueprint_seed_writer.py` over changing callers first.
- Keep artifact schemas simple JSON dictionaries with explicit `schema_version` fields.
- Preserve backward compatibility with existing tests by adding fields rather than renaming existing report keys.
- Use source refs in sidecar reports where module schemas do not allow extra keys.

## Risks

| Risk | Mitigation |
|---|---|
| Seed files duplicate data from module context | Treat seed files as toolkit support artifacts with source refs and materialization hints, not gameplay runtime state. |
| Monster seed extraction over-promotes scene entities | Use conservative hints and preserve source refs; do not create monster stat files in this slice. |
| Write classification breaks existing mocked tests | Keep existing `seed_status` values where possible and add degraded/failed only for actual write/skipped-file cases. |
| Scope creep into GUI/build routes | Restrict this slice to seed writer and tests except minimal constants/helpers if necessary. |

## Success Criteria

1. Provider-free seed writer emits canonical module files plus `npcs_seed.json`, `monsters_seed.json`, and seed source report.
2. Dry-run lists all planned artifacts and writes nothing.
3. Required write failure fails or blocks the seed result.
4. Optional artifact write failure degrades with explicit warning.
5. Numillian-like blueprint tests prove source location order and source NPC seed preservation.
