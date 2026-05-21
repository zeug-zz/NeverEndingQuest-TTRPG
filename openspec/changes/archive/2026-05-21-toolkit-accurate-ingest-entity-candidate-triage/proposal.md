## Why

Accurate ingest currently lets deterministic extraction candidates flow into canonical module entities too early. This allows prose fragments such as `but this is not true` to become NPC-like records while valid but underbound source NPCs such as Dog-Growl, Book-shut, and Deflation can lose location context.

This change adds an explicit entity-candidate triage layer before builder blueprint generation so Python can preserve source evidence while rejecting or reclassifying narrative phrases and requiring kept NPCs to carry source-backed bindings.

## What Changes

- Add a source-backed candidate triage contract for deterministic entity candidates produced during accurate ingest.
- Persist triage decisions in a reviewable report artifact before blueprint generation.
- Filter or reclassify narrative phrases so they cannot appear in NPC rosters, area NPC lists, media queues, or source-fidelity expected NPC lists.
- Require kept NPC candidates to include at least one useful binding: location, plot, faction, or explicit source role.
- Wire triage decisions into builder blueprint generation without replacing existing identity resolution or source graph artifacts.
- Add Numillian regressions for `but_this_is_not_true` rejection and Rookery Kenku preservation.
- SHOULD preserve existing Phase 2 LLM classification work; this change is accurate-ingest source-candidate triage, not a replacement for combatant/scene-illusion classification.

## Capabilities

### New Capabilities

- `toolkit-accurate-ingest-entity-candidate-triage`: Defines candidate adjudication, allowed decisions/types, required persisted report shape, and Numillian false-positive/underbound-entity regressions.

### Modified Capabilities

- `toolkit-builder-blueprint-generation`: Blueprint generation must consume triage decisions so rejected narrative phrases cannot become canonical blueprint entities and kept NPCs preserve source-backed bindings.

## Impact

- Affected code: `utils/toolkit_builder_blueprint.py`, `utils/toolkit_homebrew_normalizer.py`, `utils/toolkit_source_graph_synthesis.py`, and likely a new helper such as `utils/toolkit_entity_candidate_triage.py`.
- Affected artifacts: `identity_resolution_report.json`, `builder_blueprint.json`, `builder_blueprint_report.json`, and a new or nested triage report artifact.
- Affected tests: accurate-ingest source graph/blueprint/Numillian tests and any route tests that inspect blueprint coverage.
- MUST remain backward compatible with legacy packets and existing concept builder flows that do not have triage artifacts.
- Provider outage recovery: any LLM or cached adjudication seam added by this change MUST degrade safely and MUST NOT promote rejected deterministic narrative phrases into actor records.
