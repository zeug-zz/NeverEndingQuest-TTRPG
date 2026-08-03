## Why

Well of Ruin exposed an accurate-ingest source-atom typing failure after the structural-repair slice: table headings, one-word effect labels, and effect prose can be promoted into required `npc` atoms. The final build then reports blockers such as `Required npc 'Awaken' not found in module` or `Required npc 'Mundane objects worth at least 1 gp become sentient and hostile.' not found in module` even though these are trap/table mechanics, not NPCs.

This is an interim patch after `toolkit-accurate-ingest-modulebuilder-structural-repair` and before returning to `toolkit-accurate-ingest-llm-builder-final-editor` step 7.3. The goal is to prevent bogus non-actor source material from poisoning the blueprint NPC roster and final build-fidelity blockers, while preserving true NPC extraction for modules such as Numillian.

## What Changes

Contract Layer (MUST):

- Accurate-ingest source extraction SHALL NOT promote trap/table effect labels, table effect prose, or one-word mechanic verbs into required NPC atoms.
- Entity triage SHALL reject or reclassify non-actor table/effect/prose candidates before blueprint NPC roster construction.
- Blueprint NPC roster construction SHALL exclude rejected and non-actor triage decisions from required NPC coverage.
- Final reconciliation briefs SHALL include compact source evidence and generated-module summary when available, so the final editor does not receive empty evidence for editorial blockers.
- Structural repair routing from `toolkit-accurate-ingest-modulebuilder-structural-repair` SHALL remain intact: fatal structural categories still skip final-editor invocation.

Guidance Layer (SHOULD):

- Prefer deterministic prefilters before LLM triage where text is obviously a table/effect/prose fragment.
- Keep true named NPCs from table cells when the table header indicates identity (`Name`, `NPC`, `Character`, `Creature`, `Faction`) and the candidate passes existing name heuristics.
- Preserve non-actor material as mechanics, trap rules, DM guidance, or ignored source evidence rather than deleting source evidence entirely.
- Keep provider-free regression tests first; no live provider call should be required to prove this fix.

## Capabilities

### New Capabilities

- `accurate-ingest-table-effect-npc-prefilter`
- `accurate-ingest-entity-triage-nonactor-prefilter`
- `accurate-ingest-blueprint-npc-roster-triage`
- `accurate-ingest-final-reconciliation-evidence-brief`
- `accurate-ingest-triage-regression-tests`

### Modified Capabilities

- None. This is an additive follow-up around source atom typing and final-editor evidence quality.

## Impact

Affected code areas:

- `utils/toolkit_source_manifest.py` for table-cell entity extraction and likely-name rejection.
- `utils/toolkit_entity_candidate_triage.py` for deterministic non-actor prefiltering.
- `utils/toolkit_builder_blueprint.py` only if additional roster safety is needed beyond current triage filtering.
- `utils/toolkit_final_reconciliation.py` for evidence-rich brief construction.
- `web/extensions/toolkit_homebrew_packet_builder.py` only if additional artifacts need to be passed into the brief builder.
- Tests under `scripts/`, especially source-graph, triage, blueprint, final-reconciliation, and structural routing suites.

Rollout risks:

- True NPCs in dense tables could be filtered too aggressively. Mitigation: preserve table-cell extraction for identity-like headers and add Numillian parity tests.
- Mechanic labels may disappear from all downstream evidence. Mitigation: classify as mechanic/table effect or preserve in source refs rather than required NPC roster.
- Final reconciliation could become too powerful if brief surfaces widen. Mitigation: keep editable surfaces canonical and exclude runtime/source/middle artifacts.

Fallback strategy:

- If a candidate cannot be confidently classified as a real actor, fail safe by excluding it from required NPC coverage and preserving source evidence as mechanics/DM guidance when possible. The build can still surface editorial blockers for real missing playable elements.

Merge-safety and compatibility:

- Single-player runtime behavior is unaffected; this is toolkit accurate-ingest build-time behavior.
- Existing structural repair and final-editor validation gates remain authoritative.
- Do not change benchmark thresholds or weaken source-fidelity scoring.
