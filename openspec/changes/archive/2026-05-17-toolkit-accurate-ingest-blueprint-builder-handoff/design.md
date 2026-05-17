## Context

The accurate-ingest pipeline now has planned or implemented artifacts for source extraction, synthesis, packet generation, fidelity audit, and bounded repair. Those artifacts reduce normalization loss, but they do not yet constrain the builder. Current builder flow still depends on `builder_narrative.md` and `ModuleBuilder.build_module(...)`, which can treat the input like a creative concept instead of a source-locked build plan.

Phase 4 introduces a builder blueprint layer. The blueprint is not a final module schema and is not a build-time audit. It is a source-backed construction plan derived from Phase 2-3 artifacts, designed to make the existing builder handoff explicit, reviewable, and hard to misinterpret.

## Contract Layer (MUST)

- Blueprint generation MUST run after normalized packet synthesis and Phase 3 fidelity audit/repair.
- Blueprint generation MUST consume source-backed artifacts, not raw model prose alone.
- Blueprint generation MUST refuse to proceed when final fidelity status is `blocked`, `failed`, or missing unless an explicit legacy fallback mode is active.
- Blueprint generation MUST preserve canonical source display names and source atom IDs where available.
- Blueprint generation MUST represent required source locations, NPCs, plot beats, puzzle/trial chains, clue dependencies, monster/encounter plans, important items, and tone markers.
- Builder narrative generation MUST be derived from `builder_blueprint.json`, not from a 3-7 line summary.
- Builder narrative MUST include explicit source lock instructions, required rosters, source plot topology, puzzle rules, clue graph, and forbidden major inventions.
- `builder_input.json` MUST include blueprint identity, blueprint path, fidelity status, source lock settings, and source artifact references when blueprint handoff is active.
- Existing legacy builder handoff MUST remain available when accurate-ingest blueprint handoff is disabled or unavailable.
- User-facing Python log/console text introduced by implementation MUST be ASCII-only.

## Guidance Layer (SHOULD)

- Blueprint generation SHOULD be deterministic Python transformation where possible.
- LLM usage SHOULD be avoided for core blueprint structure; if used later, it should only summarize or format fields already present in source artifacts.
- Blueprint entries SHOULD include source refs or source atom IDs for review and later build fidelity gates.
- Blueprint status SHOULD distinguish `ready`, `blocked_by_fidelity`, `missing_artifacts`, `invalid_packet`, and `generation_failed`.
- Source locks SHOULD be explicit enough for later prompts and audits to detect violations.
- Builder narrative SHOULD be verbose enough to preserve source rosters and topology, even if it is longer than the legacy concise builder narrative.
- Packet builder integration SHOULD be minimal and merge-safe: prefer adding artifact metadata and handoff selection over restructuring upstream builder internals.

## Artifact Contract

New workspace artifacts planned by this change:

- `builder_blueprint.json` - source-backed builder construction plan.
- `builder_blueprint_report.json` - compact generation status, input artifact hashes/status, coverage counts, and refusal reasons.

Existing artifacts affected by implementation:

- `builder_narrative.md` should become source-locked and blueprint-derived when blueprint handoff is active.
- `builder_input.json` should include blueprint and source-lock metadata when available.
- `normalization_report.json` may include compact blueprint handoff status if that is the least invasive reporting seam.

## Blueprint Shape

The blueprint should use a stable schema similar to:

```json
{
  "blueprint_version": "source_faithful_builder_blueprint.v1",
  "source_hash": "...",
  "normalized_packet_hash": "...",
  "fidelity_status": "clean|repaired|degraded",
  "blueprint_status": "ready",
  "module": {
    "title": "The Hidden City of Numillian",
    "summary": "source-grounded module summary",
    "tone_profile": {
      "markers": [],
      "forbidden_tone_replacements": []
    }
  },
  "source_lock": {
    "canonical_names_locked": true,
    "required_atom_omission_blocks_build": true,
    "invented_major_entities_forbidden": true,
    "replacement_plotlines_forbidden": true,
    "puzzle_rule_rewrite_forbidden": true
  },
  "area_plan": [],
  "location_roster": [],
  "npc_roster": [],
  "plot_graph": [],
  "puzzle_graph": [],
  "clue_graph": [],
  "encounter_plan": [],
  "item_roster": [],
  "tone_requirements": [],
  "source_refs": [],
  "warnings": []
}
```

## Blueprint Entry Guidance

Location entries should include:

- Source atom ID.
- Original source name and display name.
- Parent source section or area.
- Required/major/minor criticality.
- NPCs, monsters, treasure, traps, doors, checks, clues, and connectivity hints.
- Source refs.

NPC entries should include:

- Source atom ID.
- Original source name and aliases.
- Role, faction, personality cues, dialogue cues, relationship ties, and location bindings.
- Scene state guidance: present, hidden, lore-only, hostile, allied, ambiguous.
- Source refs.

Plot entries should include:

- Source atom ID or topology node ID.
- Beat title, trigger, dependencies, required location/NPC/item, outcomes, failure states, and next beats.
- Whether the beat is mainline, optional, climax, ending, or epilogue.

Puzzle/clue entries should include:

- Setup, player-facing prompt, rules, solution, failure consequences, unlocks, and required clue dependencies.
- Explicit instruction that rules must be preserved.

## Builder Narrative Contract

The source-locked narrative should be generated from the blueprint and include sections in a predictable order:

1. `SOURCE-FAITHFUL BUILD LOCK`
2. `MODULE IDENTITY AND TONE`
3. `REQUIRED LOCATION ROSTER`
4. `REQUIRED NPC ROSTER`
5. `PLOT TOPOLOGY`
6. `PUZZLE AND TRIAL RULES`
7. `CLUE GRAPH`
8. `ENCOUNTER AND MONSTER PLAN`
9. `ITEM AND TREASURE PLAN`
10. `FORBIDDEN INVENTIONS AND REPLACEMENTS`
11. `ALLOWED COMPRESSION OR MERGE NOTES`

The narrative may be longer than the legacy concise builder narrative. Token budget pressure should be handled by deterministic compact formatting, not by dropping required source atoms.

## Builder Input Handoff

`builder_input.json` should include a compact block similar to:

```json
{
  "builder_input_version": "builder_input.v2",
  "handoff_mode": "source_blueprint",
  "builder_narrative_path": ".../builder_narrative.md",
  "builder_blueprint_path": ".../builder_blueprint.json",
  "blueprint_status": "ready",
  "fidelity_status": "clean",
  "source_lock": {
    "canonical_names_locked": true,
    "invented_major_entities_forbidden": true
  },
  "source_artifacts": {
    "source_graph": ".../source_graph.json",
    "identity_resolution_report": ".../identity_resolution_report.json",
    "plot_topology_report": ".../plot_topology_report.json",
    "normalization_fidelity_report": ".../normalization_fidelity_report.json"
  }
}
```

Legacy fields should remain present or readable as needed for existing consumers.

## Orchestration

1. Load `source_graph.json`, `identity_resolution_report.json`, `plot_topology_report.json`, `source_graph_synthesis_report.json`, `normalized_packet.json`, `normalization_fidelity_report.json`, and `normalization_report.json` when present.
2. Evaluate fidelity precheck.
3. If fidelity precheck fails in accurate-ingest blueprint mode, persist `builder_blueprint_report.json` with refusal status and stop before builder handoff.
4. Build blueprint rosters and graphs from Phase 2-3 artifacts.
5. Persist `builder_blueprint.json` and `builder_blueprint_report.json`.
6. Serialize blueprint into source-locked `builder_narrative.md`.
7. Persist `builder_input.json` with blueprint metadata and source-lock settings.
8. Update packet builder execution to prefer blueprint-backed narrative when `builder_input.handoff_mode == "source_blueprint"` and blueprint status is ready.

## Degraded Behavior

- If source artifacts are missing, blueprint generation reports `missing_artifacts` and does not claim readiness.
- If fidelity status is blocked or failed, blueprint generation reports `blocked_by_fidelity`.
- If optional minor artifacts are missing but required source graph, packet, and fidelity report are available, blueprint generation may proceed with warnings.
- If blueprint narrative persistence fails, builder handoff fails closed for accurate-ingest mode.
- If accurate-ingest blueprint mode is disabled, legacy builder narrative behavior remains available.

## Rollback

Rollback is straightforward: disable blueprint handoff and continue using legacy `builder_narrative.md`. Existing blueprint artifacts are additive and safe to ignore.
