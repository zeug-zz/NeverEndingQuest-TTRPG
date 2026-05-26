# Change: Accurate-Ingest Monster Encounter Materialization

## Why

The accurate-ingest recovery chain now preserves Numillian NPCs, locations, puzzles, lore, and tone, and the archived generator-source-lock slice propagates source monster references and encounter seeds into source-enhanced ModuleBuilder context.

The remaining gap is artifact materialization. Source monster references such as Duergar, Alhoon, Illithid, Homunculus, Kenku, Druid, Were-possum, Were-trout, Were-bear, Nothic, Vampire, and Charion can reach the builder handoff, but they can still disappear before module-local monster files, encounter plans, and toolkit reports are finalized.

This change closes that gap with a deterministic, reuse-first materialization contract. It does not replace ModuleBuilder, does not change the benchmark scanner, and does not require a production Numillian rebuild.

## What Changes

- Add provider-free tests and helpers that consume source monster refs and encounter seeds from source-enhanced accurate-ingest artifacts.
- Materialize unambiguous source monster refs into module-local `monsters/*.json` artifacts using reuse-first resolution from existing module/SRD/bestiary-compatible sources.
- Bind encounter seeds or encounter-plan entries to canonical monster identities when source refs are unambiguous.
- Report planned, generated, reused, skipped, and unresolved monster/encounter refs in deterministic build artifacts.
- Preserve unresolved source monster refs as explicit blockers or warnings instead of silently dropping them.

## Non-Goals

- Do not run a production rebuild of `modules/The_Hidden_City_of_Numillian/` in this change.
- Do not change benchmark thresholds, benchmark fixture data, or benchmark scanner logic.
- Do not call LLM providers, ModuleBuilder live generation, MMG/media generation, or runtime combat encounter creation from tests.
- Do not invent replacement monsters to satisfy source counts.
- Do not promote NPC/source-character names into monster artifacts without source evidence that they are monsters or combatants.
- Do not weaken validation, readiness, publishability, source-fidelity, or build-fidelity gates.

## MUST Constraints

- Source monster refs SHALL be materialized by reuse-first resolution or recorded as explicit unresolved refs.
- Encounter seeds SHALL retain monster bindings when source monster refs are present and unambiguous.
- Materialized monster artifacts SHALL be schema-valid or the materialization step SHALL fail/degrade with explicit diagnostics.
- The implementation SHALL NOT invent replacement monster identities or silently drop required source monster refs.
- Legacy concept builds and no-source accurate-ingest paths SHALL remain compatible and SHALL NOT emit false monster blockers.
- Tests SHALL be deterministic and provider-free.

## SHOULD Guidance

- Prefer a small helper module around existing monster authority and hydration utilities before adding new builder architecture.
- Prefer temp workspace fixtures for module writes; avoid mutating production Numillian artifacts in tests.
- Prefer narrow report shape additions over broad toolkit report rewrites.
- Use existing monster schema/template data where possible instead of hand-authored stat blocks.

## Risks

- Monster names may be ambiguous between NPCs, factions, classes, and creatures. Mitigation: require source evidence and keep ambiguous refs unresolved.
- Reuse-first resolution may not cover odd source monsters. Mitigation: report unresolved refs explicitly and defer provider/stat synthesis to a later reviewed slice.
- Report changes may create stale disagreement with existing gates. Mitigation: add compatibility tests and avoid changing publication precedence in this slice.

## Rollback

Revert the materialization helper and report additions while preserving source monster/encounter handoff tests. Existing ModuleBuilder and source-lock behavior should continue to function because this change is additive after handoff.

## Dependencies

- `toolkit-accurate-ingest-modulebuilder-handoff` is archived.
- `toolkit-accurate-ingest-generator-source-locks` is archived.
- `plans/accurate-ingest-fix.md` identifies this as the next recovery slice.
