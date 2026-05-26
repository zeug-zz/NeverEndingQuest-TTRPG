# Accurate Ingest GUI Builder Recovery Plan

**Status:** Active roadmap; backstage audit MVP, builder-audit briefing, ModuleBuilder handoff, and generator source locks archived; next scaffold is monster/encounter materialization
**Created:** 2026-05-19  
**Rewritten:** 2026-05-20  
**Updated:** 2026-05-26
**Scope:** Recover Module Builder GUI ingest by enhancing the existing LLM ModuleBuilder orchestration with accurate-ingest source truth, not replacing it with a deterministic template writer.  
**Primary Source Case:** `Local_Docs/modules/hombrew/modules/The Hidden City of Numillian.md`  
**Target Module:** `modules/The_Hidden_City_of_Numillian/`

---

## Executive Summary

The accurate-ingest roadmap remains directionally correct, and the last month of toolkit work should be preserved. The architectural drift to correct is narrower and clearer than a full rewrite:

> Accurate ingest should enhance the existing LLM ModuleBuilder path with source-faithful structured context. It should not replace ModuleBuilder with a deterministic Python-generated adventure template.

The current GUI path has become unsafe because `ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD` routes accurate-ingest jobs into `utils/toolkit_blueprint_seed_writer.py`, while `utils/toolkit_blueprint_enrichment.py` still has no real provider orchestration. That means the GUI can materialize a thin, schema-oriented skeleton with empty prose fields, then send it through readiness/finisher gates as if it were a real adventure build.

This plan restores the original accurate-ingest intent:

```text
Source MD/PDF
  -> Python source graph, section chunks, identity/topology/fidelity artifacts
  -> LLM bounded source extraction and blueprint enrichment
  -> Python validates source locks and structural contracts
  -> existing ModuleBuilder orchestration generates the NEQ module
  -> Python repairs/validates schema, coordinates, connectivity, media, reports
  -> final Homebrewery MODULE_SUMMARY.md is derived from completed module JSON
```

The deterministic seed writer is not deleted. It is retained as support tooling: dry-run preview, fixture generation, fallback skeleton, source-vs-output comparator, and artifact repair helper. It is not the default authoring path for human adventure content.

### Current Disposition After 2026-05-26 Archives

The recovery chain has moved past audit scaffolding and generator-level source-lock hardening into source monster/encounter materialization:

- `toolkit-accurate-ingest-backstage-audit-mvp` is archived.
- `toolkit-accurate-ingest-builder-audit-briefing` is archived.
- `toolkit-accurate-ingest-modulebuilder-handoff` is archived.
- `toolkit-accurate-ingest-generator-source-locks` is archived.
- Default accurate-ingest packet builds are now locked to the source-enhanced ModuleBuilder handoff path when no explicit seed writer mode is supplied.
- `builder_input` now carries source NPC, location, puzzle/challenge, monster reference, encounter seed, tone, source-lock, and artifact metadata before ModuleBuilder execution.
- ModuleBuilder and sub-generator prompts now receive compact source-lock context for overview, area naming, location, and plot generation.

The next recovery slice is `toolkit-accurate-ingest-monster-encounter-materialization`. It should convert the now-visible source monster references and encounter seeds into provider-free monster materialization/binding contracts before any production Numillian rebuild.

### Current Numillian Monster Gap

Numillian currently has no `monsters/*.json` files because the completed preservation chain focused on NPC, location, puzzle, lore, and tone fidelity. The source pipeline sees monster-like references and encounter seeds, and the archived generator-source-lock slice now propagates them into `builder_input` and ModuleBuilder context. The remaining gap is materialization and binding:

- `normalized_packet.json` contains `monster_refs` such as `Duergar`, `Alhoon`, `Illithid`, `Homunculus`, `Kenku`, `Druid`, `Were-possum`, `Were-trout`, `Were-bear`, `Nothic`, `Vampire`, and `Charion`.
- `normalized_packet.json` contains five `encounter_seeds`.
- `builder_input.json` carries source monster refs and encounter seeds for source-enhanced builds.
- `builder_blueprint.json` may still have `encounter_plan` entries whose `monsters` arrays are empty.
- `monsters_seed.json` may still contain an empty `monsters` list.
- `toolkit_build_report.json` reports `encounters_planned: 5`, `monsters_generated: 0`, and warns that enrichment should add monster stats.

This is not currently caught by the Numillian benchmark because `accurate_ingest_benchmark_report.json` scores NPC, location, puzzle, lore, and tone preservation, not monster preservation. The next slice should add deterministic monster materialization and encounter binding tests first, then generate/reuse module-local monster artifacts without changing benchmark thresholds or scanner logic.

---

## Non-Negotiable Direction

### Do Not Replace ModuleBuilder

The existing `core/generators/module_builder.py` orchestration remains the primary creative build path for GUI adventure ingest.

Do not describe it as deprecated. Avoid the term "legacy builder" except when referring to old behavior in historical notes. Use:

- `existing ModuleBuilder orchestration`
- `LLM ModuleBuilder path`
- `source-enhanced ModuleBuilder handoff`

### Do Enhance ModuleBuilder

Accurate ingest should make ModuleBuilder better by giving it source-faithful structured input:

- Canonical NPC names and aliases.
- Required keyed locations and source order.
- Plot topology, puzzle chains, clue dependencies, endings, and failure states.
- Encounter and monster references.
- Tone markers and forbidden invention warnings.
- Source excerpts and evidence references.
- Build constraints that prevent replacement plotlines and major invented entities.

### Do Preserve Existing Toolkit Work

The following work remains valuable and should be kept:

| Existing Work | Recovery Role |
|---|---|
| `source_manifest.json` / `source_graph.json` | Source truth and evidence spans. |
| Section-bounded extraction scaffolds | Input chunks for LLM fact extraction. |
| Identity resolution | Canonical names, aliases, duplicate detection. |
| Plot topology report | Plot/puzzle/clue/endings contract. |
| Normalization fidelity reports | Automated source preservation diagnostics and blocker surfacing. |
| Fidelity review UI | Optional inspection panel for diagnostics, waivers, and debugging. It is not a mandatory approval gate. |
| Builder blueprint v1/v2 | Source-faithful build contract for ModuleBuilder. |
| Build fidelity gates | Post-build source preservation detector. |
| Readiness and publishability gates | Final publication pipeline. |
| MMG/media handoff work | Final module media completion. |
| Homebrewery summary writer | Final derived presentation artifact. |
| Deterministic seed writer | Support/fallback/comparison tooling, not primary author. |

---

## Current Failure Mode

### What Works Or Is Valuable

The old upstream-style Module Builder GUI could produce playable modules from one broad concept/narrative handoff. Converted modules such as `The_Thornwood_Watch`, `Keep_of_Doom`, `A_Pottsfield_Burial`, `Into_the_Deepvault`, and `Murder_at_the_Drowning_Lass` prove the general builder pipeline, readiness gates, media handoff, semantic checks, and publication tooling can produce usable adventures.

The problem with those early ingests was not GUI mechanics. It was source fidelity. The builder was given a compressed summary of the uploaded adventure, so it filled gaps creatively and drifted from the original source.

### What Broke

The current accurate-ingest GUI path now risks the opposite failure:

```text
Old problem:
  Too much LLM creative freedom from too little source truth
  -> playable but source-inaccurate modules

Current problem:
  Too much deterministic Python materialization from too little interpretation
  -> source-named but thin/unplayable skeleton modules
```

Observed code-level issue:

- `model_config.py` currently enables `ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD`.
- `web/extensions/toolkit_homebrew_packet_builder.py` routes ready v2 blueprint builds to `_execute_seed_writer_build(...)`.
- `_execute_seed_writer_build(...)` calls `materialize_module_from_blueprint(...)` instead of `ModuleBuilder.build_module(...)`.
- `utils/toolkit_blueprint_seed_writer.py` emits many valid-looking files, but important adventure fields remain empty or skeletal.
- `utils/toolkit_blueprint_enrichment.py` still says provider orchestration is not implemented and returns no patches.
- `MODULE_SUMMARY.md` is generated after the fact and is explicitly derived output, not a source-fidelity repair mechanism.

### Why This Is Architecturally Wrong

Python regex and deterministic structural heuristics cannot faithfully reproduce a human-authored tabletop adventure. They can preserve names, source refs, IDs, coordinates, maps, schema contracts, and validation boundaries. They cannot reliably interpret mood, character motives, puzzle intent, clue semantics, adventure pacing, or hidden plot relationships at human-DM quality.

The LLM must still perform bounded interpretation and prose synthesis. The correction is to constrain and verify the LLM, not remove it from the authoring path.

---

## Revised Target Architecture

### High-Level Flow

```text
               +--------------------+
               | Uploaded MD / PDF  |
               +---------+----------+
                         |
                         v
          +--------------+---------------+
          | Python source truth pipeline |
          | manifest, graph, chunks      |
          +--------------+---------------+
                         |
                         v
       +-----------------+------------------+
       | LLM bounded source extraction      |
       | NPCs, locations, plots, puzzles    |
       | monsters, items, tone, clues       |
       +-----------------+------------------+
                         |
                         v
       +-----------------+------------------+
       | Python blueprint validator         |
       | source locks, refs, coverage       |
       +-----------------+------------------+
                         |
                         v
       +-----------------+------------------+
       | Existing ModuleBuilder orchestration|
       | source-enhanced prompts/context    |
       +-----------------+------------------+
                         |
                         v
       +-----------------+------------------+
       | Python structural finalization      |
       | coordinates, maps, schemas, BU      |
       +-----------------+------------------+
                         |
                         v
       +-----------------+------------------+
       | Readiness, media, publishability    |
       | source fidelity, benchmark, reports |
       +-----------------+------------------+
                         |
                         v
       +-----------------+------------------+
       | MODULE_SUMMARY.md derived output    |
       +------------------------------------+
```

### Ownership Boundaries

| Layer | Owner | Responsibility |
|---|---|---|
| Source text storage | Python | Store original upload and source hash. |
| Source graph | Python + bounded LLM facts | Preserve evidence spans and typed atoms. |
| Entity/topology interpretation | LLM proposes, Python validates | Identify NPCs, keyed locations, plots, puzzles, clues, endings. |
| Build contract | Python | Validate blueprint, source locks, coverage, allowed omissions. |
| Adventure prose and playable detail | Existing ModuleBuilder LLM stages | Write rich module JSON content from source contract. |
| IDs, schemas, maps, BU/runtime split | Python | Enforce NEQ structural rules and publication contracts. |
| Fidelity scoring | Python | Detect omissions, replacements, unsupported inventions. |
| Operator intervention | GUI | Optional blocker inspection, waiver decisions, and debugging when automated gates fail. Normal clean builds should not pause for approval. |
| Module summary | Python + LLM summary helpers | Derived from final module JSON only. |

---

## Existing ModuleBuilder Enhancement Strategy

### Current ModuleBuilder Shape

`ModuleBuilder.build_module(initial_concept)` already orchestrates the creative build:

1. Creates module directory structure.
2. Calls `ModuleGenerator.generate_module(...)` for module overview/world map.
3. Generates areas from world map.
4. Generates locations for each area.
5. Finalizes location IDs/connections.
6. Generates plots.
7. Unifies plots into `module_plot.json`.
8. Updates area plot hooks.
9. Creates party tracker.
10. Creates summary.
11. Reconciles NPC names.
12. Validates module.
13. Creates `_BU.json` backups.

This is the right path to enhance. It already knows how to produce full NEQ module artifacts, but it needs source-faithful constraints and richer handoff content.

### Enhancement Point 1: Builder Input Contract

Replace the current lossy `builder_narrative` with a source-enhanced `builder_input` that contains:

- `source_blueprint_version`
- `source_hash`
- `source_rights_class`
- `module_identity`
- `required_locations`
- `required_npcs`
- `required_plot_beats`
- `puzzle_chains`
- `clue_dependencies`
- `encounter_plan`
- `item_roster`
- `tone_requirements`
- `forbidden_inventions`
- `allowed_compression_notes`
- bounded source excerpts

This can still be serialized into a text prompt for the current `ModuleBuilder.build_module(initial_concept)` entrypoint at first. Later, if needed, `ModuleBuilder` can accept a typed `source_blueprint` argument without changing the external GUI contract.

### Enhancement Point 2: ModuleGenerator Source Contract

`ModuleGenerator.generate_module(...)` should be told:

- Use the source title unless explicitly overridden by operator action.
- Build `worldMap` areas from source area/keyed-location groupings.
- Preserve required NPC names in module context.
- Preserve source tone markers.
- Do not invent replacement main factions or villains when source provides them.
- If a source entity cannot be placed, record it as an explicit unresolved item rather than replacing it.

### Enhancement Point 3: Area And Location Generation

`AreaGenerator` and `LocationGenerator` should receive source-bound constraints:

- Required location names by area.
- Original map key number or heading order.
- Source location excerpts.
- Required NPC/monster/item/clue bindings per location.
- Puzzle/trap/DC instructions from source.
- Connectivity hints and map-key adjacency when available.

The LLM remains responsible for prose and DM-facing richness, but within a locked roster.

### Enhancement Point 4: Plot Generation

`PlotGenerator` should receive:

- Required plot beats in source order.
- Optional/branching beat classification.
- Puzzle chain setup/rules/solution/failure consequences.
- Clue dependencies.
- Ending variants.
- Required NPC/location associations.

It should enrich descriptions and side quests without replacing the source topology.

### Enhancement Point 5: Post-Builder Source Fidelity Repair

After ModuleBuilder produces the module:

- Python compares output to blueprint/source graph.
- Missing required entities become blockers.
- Rename drift is corrected only through approved aliases or deterministic canonicalization.
- Empty narrative fields can enter LLM patch enrichment, but structure cannot be rewritten without explicit review.
- Build fidelity report is persisted and propagated into final module artifacts.

---

## Deterministic Seed Writer Reclassification

### Keep It

Do not delete or abandon `utils/toolkit_blueprint_seed_writer.py`. It represents useful work.

### Do Not Use It As Default GUI Authoring Path

The seed writer should not be the default accurate-ingest GUI builder path while it produces skeletal adventure content and enrichment is not implemented.

### Revised Roles

The seed writer should become:

1. **Dry-run preview tool**
   - Shows what source structure the blueprint currently understands.
   - Useful in optional diagnostics UI before or after a build.

2. **Fixture generator**
   - Creates deterministic test modules for source-fidelity and publication-gate tests.
   - Useful for reproducible CI and benchmark baselines.

3. **Fallback skeleton path**
   - Explicit operator choice when provider calls are unavailable.
   - Must be labeled as structure-only/degraded, not publishable unless later enriched.

4. **Comparator**
   - Seed output can represent "minimum required source structure".
   - ModuleBuilder output can be compared against it for omitted names/locations/plot beats.

5. **Artifact repair helper**
   - Can emit or repair support artifacts such as `npcs_seed.json`, `monsters_seed.json`, `seed_source_report.json`, canonical backup files, and map scaffolds.

6. **Overwrite safety test subject**
   - Because it writes deterministic files, it is useful for testing rebuild/overwrite gates without incurring LLM cost.

### Required Status Labels

Seed-writer builds must report honestly:

- `seed_status=success` only when all required canonical files were written.
- `seed_status=degraded` when optional files fail or content is knowingly thin.
- `seed_status=failed` when required canonical files fail.
- `build_mode=blueprint_seed_support` or `blueprint_seed_fallback`, not `packet_workspace_v2` as if it were the normal authoring path.

---

## LLM Blueprint Enrichment Strategy

### Problem To Solve

The current blueprint contains useful rosters and locks, but many fields are empty or shallow:

- NPC descriptions, motives, secrets, relationships.
- Location descriptions, DM instructions, DC checks, doors, traps, loot, clue placement.
- Plot beat descriptions and consequences.
- Puzzle rules and solutions.
- Monster/encounter purposes.
- Tone and pacing guidance.

These are exactly where the LLM is valuable.

The current deterministic extraction also promotes some textual phrases into the wrong semantic category. Numillian exposes the failure clearly:

```json
"but_this_is_not_true": {
  "name": "but this is not true",
  "role": "truth-revealing note in the shared consciousness with Shuluth",
  "faction": "",
  "appears_in": []
}
```

This phrase comes from source narration about Shuluth's fabricated mindscape:

```text
The illithid creates the impression that the players are no longer within its fabricated mindscape, but this is not true.
```

It is not an NPC, faction, monster, location, item, clue-object, or encounter actor. It is a narrative assertion. Regex-style candidate extraction can detect text spans, but it cannot reliably decide semantic role.

The same source section also shows a subtler case:

```text
The Rookery ... is inhabited by Dog-Growl, Book-shut, and Deflation, three Kenku...
```

Dog-Growl, Book-shut, and Deflation are real named residents/NPCs, but the current blueprint leaves `appears_in` empty and does not bind them to `The Rookery`. The correct outcome is not to drop them; it is to classify them as minor/source NPCs, bind them to their source location, and preserve enough role/context for ModuleBuilder to write them properly.

Therefore the recovery must handle two distinct extraction failures:

1. **False-positive entities** - narrative phrases, emphasized clauses, table labels, headings, or prose fragments promoted to NPC/location/item records.
2. **Underbound valid entities** - real named NPCs/locations/items extracted without location binding, source role, or adventure function.

### Enrichment Must Happen Before ModuleBuilder Handoff

The first real LLM enrichment should not patch a finished skeletal module. It should enrich the source blueprint so ModuleBuilder receives a rich, structured, source-backed design brief.

Recommended artifact:

```text
builder_blueprint_enriched.json
```

or versioned in-place:

```json
{
  "blueprint_version": "source_faithful_builder_blueprint.v3",
  "blueprint_status": "ready",
  "source_hash": "...",
  "module": {},
  "area_plan": [],
  "location_roster": [],
  "npc_roster": [],
  "plot_graph": [],
  "puzzle_graph": [],
  "clue_graph": [],
  "encounter_plan": [],
  "item_roster": [],
  "source_lock": {},
  "enrichment": {
    "status": "complete|degraded|failed|skipped",
    "passes": [],
    "coverage": {},
    "warnings": [],
    "blockers": []
  }
}
```

### Bounded Extraction Passes

Use smaller prompts rather than one monolithic source handoff.

Recommended passes:

1. **NPC pass**
   - Input: source chunks where NPC names appear, identity report, source refs.
   - Output: description, role, faction, motives, secrets, relationships, location bindings.
   - Must classify each candidate as `true_npc`, `scene_actor`, `monster_actor`, `item_or_clue`, `location_name`, `faction_name`, `narrative_phrase`, or `reject`.
   - Must reject narrative assertions like `but this is not true` even if capitalization, emphasis, heading position, or regex tokenization makes them look name-like.
   - Must preserve valid minor NPCs such as Dog-Growl, Book-shut, and Deflation, with `appears_in` bound to `The Rookery` and source refs attached.

2. **Location pass**
   - Input: keyed map sections and nearby narrative text.
   - Output: description, DM instructions, features, clues, traps, DC checks, doors, loot, NPCs, monsters.

3. **Plot pass**
   - Input: plot topology, source graph plot atoms, adventure overview sections.
   - Output: plot beat descriptions, triggers, outcomes, dependencies, failure states, endings.

4. **Puzzle/clue pass**
   - Input: puzzle chains, clue dependencies, relevant location excerpts.
   - Output: setup, rules, solution, failure consequences, reveal chain.

5. **Encounter/monster pass**
   - Input: encounter atoms, monster mentions, location bindings.
   - Output: encounter purpose, avoidability, social/combat path, monster names, source refs.

6. **Tone/style pass**
   - Input: tone markers and representative excerpts.
   - Output: style guide for ModuleBuilder prompts, not new plot content.

7. **Candidate triage pass**
   - Input: all deterministic entity candidates plus source excerpts.
   - Output: keep/reclassify/reject decisions with reasons.
   - Purpose: prevent regex candidates from becoming canonical module entities until LLM adjudication and Python validation agree.

### Entity Candidate Triage Contract

Deterministic extraction may produce candidates, but candidates are not entities until adjudicated.

Every candidate should pass through a triage schema similar to:

```json
{
  "candidate_text": "but this is not true",
  "candidate_slug": "but_this_is_not_true",
  "source_ref": {...},
  "proposed_type": "npc",
  "adjudicated_type": "narrative_phrase",
  "decision": "reject",
  "reason": "This is a prose assertion about the mindscape, not an actor or entity."
}
```

For valid but underbound entities:

```json
{
  "candidate_text": "Dog-Growl",
  "candidate_slug": "dog_growl",
  "source_ref": {...},
  "proposed_type": "npc",
  "adjudicated_type": "true_npc",
  "decision": "keep",
  "location_bindings": ["The Rookery"],
  "role": "Kenku resident and composer using Shuluth-taught Qualith",
  "criticality": "minor"
}
```

Python validation should enforce:

- Rejected candidates cannot appear in `module_context.json#npcs`, area NPC lists, media queues, or source-fidelity expected NPC lists.
- Kept NPCs must have at least one of: location binding, plot binding, faction binding, or explicit source role.
- Empty `appears_in` for a source-bound NPC is a warning or blocker depending on criticality.
- Narrative phrases may become plot notes, DM instructions, clue text, or tone markers, but never actor records.
- Candidate type changes must be recorded in `identity_resolution_report.json` or an equivalent triage report.

### Patch Contract Still Applies

The existing patch-validator work should be reused. The LLM proposes structured field updates. Python validates:

- Only allowed fields may be enriched.
- Source names cannot be renamed.
- IDs cannot be changed.
- Connectivity cannot be invented without source or spatial solver approval.
- Puzzle rules cannot be rewritten contrary to source.
- Major NPCs, factions, villains, locations, and endings cannot be invented.

### Enrichment Status Must Be Truthful

Current placeholder behavior must be corrected:

- Disabled enrichment returns `skipped`.
- Enabled but unimplemented enrichment returns `not_implemented`.
- Provider failure returns `degraded` or `failed` with explicit reason.
- No provider call plus no applied patches must never return `complete`.
- Structural mutation attempts must be rejected and reported.

---

## MODULE_SUMMARY.md And Narrative Field Reuse

### Current Role

`utils/homebrewery_adventure_writer.py` currently loads final module JSON and generates Homebrewery V3 markdown. This should remain a final derived output.

### Useful Pieces To Reuse

The summary writer already knows how to traverse:

- Module context.
- NPC gallery.
- Plot overview.
- Areas and nested locations.
- Monsters.
- Treasure index.
- Cross-area connectivity.

That traversal can support a shared narrative synthesis layer.

### Revised Architecture

Create shared helpers that can emit both:

1. JSON enrichment patches for module fields.
2. Markdown sections for `MODULE_SUMMARY.md`.

Conceptual split:

```text
utils/module_narrative_synthesis.py
  -> build_npc_narrative_patch_context(...)
  -> build_location_narrative_patch_context(...)
  -> build_plot_narrative_patch_context(...)
  -> call_llm_for_json_patches(...)
  -> validate_patch_source_refs(...)

utils/homebrewery_adventure_writer.py
  -> consumes final JSON and synthesis summaries
  -> writes MODULE_SUMMARY.md
```

### Guardrail

`MODULE_SUMMARY.md` must not become source truth. It must not repair source-fidelity scores. It must not be used to hide missing source atoms.

Correct flow:

```text
source + blueprint + final module JSON -> synthesis helpers -> patches + summary
```

Incorrect flow:

```text
MODULE_SUMMARY.md -> repair module JSON -> claim source fidelity
```

---

## GUI State Machine Recovery

### Required User-Visible States

The GUI should show one coherent flow:

```text
queued
preflight
extracting_source_truth
extracting_section_facts
resolving_identity
building_topology
building_blueprint
preparing_builder_handoff
building_with_modulebuilder
build_fidelity
readiness
finishing
publishability_audit
completed | not_publishable | blocked | failed | quarantined
```

### Important Distinction

`seeding_module` should not be a normal default state. It should appear only when:

- Operator explicitly requests seed preview/fallback.
- Tests exercise seed writer behavior.
- The system is generating support artifacts, not authoring the final adventure.

### Optional Fidelity Diagnostics

The fidelity review UI must not be a mandatory approval gate for clean accurate-ingest builds. Mandatory pre-build approval was intentionally removed from the initial upload ingest flow because it adds user delay without improving normal outcomes.

The UI should exist as an optional diagnostics surface for:

- Explaining automated blockers.
- Reviewing source-fidelity warnings after or during a failed/degraded build.
- Applying explicit waivers when a degraded source-fidelity result is acceptable.
- Debugging source extraction, blueprint coverage, or build-fidelity mismatches.

Clean builds should proceed without requiring extra user clicks.

The optional diagnostics panel should summarize:

- Source atom counts.
- Section extraction status.
- Identity/topology status.
- Blueprint coverage.
- Required omissions.
- Warnings and blockers.
- Whether the current path is ModuleBuilder build, seed preview, or fallback skeleton.

---

## Source Fidelity And Publishability

### Required Artifact Propagation

The final module directory should contain or reference the source-fidelity status generated during GUI build.

Required module-level artifacts for accurate-ingest modules:

```text
source_fidelity_report.json
accurate_ingest_benchmark_report.json
toolkit_build_report.json
builder_blueprint_report.json or copied/summarized source-fidelity metadata
seed_source_report.json if seed writer support artifacts were used
```

### Publishability Composition

Publishability should compose three dimensions:

1. Readiness status.
2. Semantic/publishability status.
3. Source-fidelity status.

Worst-status-wins unless an explicit waiver contract applies.

Legacy modules without accurate-ingest artifacts should continue to report source fidelity as `unknown` and fail open.

Accurate-ingest modules with source-fidelity blockers must not publish as clean.

---

## Numillian Replacement Proof

Numillian remains the canonical proof case because it exposed the original fidelity failure.

### Source Truth

```text
Local_Docs/modules/hombrew/modules/The Hidden City of Numillian.md
```

### Production Target

```text
modules/The_Hidden_City_of_Numillian/
```

### Historical Inaccurate Ingest

If retained, `modules/The_Hidden_City_of_Numillian_v1/` is archive/comparison only. It must not be selected by module discovery, published module catalog, or default play path.

### Benchmark Expectations

The rebuilt production module must preserve:

- 13 source locations by original source names or approved alias mapping.
- Required NPC threshold from benchmark fixture.
- Trial-at-the-Door puzzle.
- Skull riddle.
- Flooding room puzzle.
- Kill-the-dog mindscape test.
- Gatepact lore.
- Kobe protection objective.
- Quirky character-driven tone.
- No generic ward-network/conspiracy replacement plot unless source-supported.

### Canonical Artifact Set

At minimum:

```text
modules/The_Hidden_City_of_Numillian/module_context.json
modules/The_Hidden_City_of_Numillian/module_context_BU.json
modules/The_Hidden_City_of_Numillian/module_plot_BU.json
modules/The_Hidden_City_of_Numillian/party_tracker_BU.json
modules/The_Hidden_City_of_Numillian/areas/*_BU.json
modules/The_Hidden_City_of_Numillian/map_*.json
modules/The_Hidden_City_of_Numillian/npcs_seed.json
modules/The_Hidden_City_of_Numillian/monsters_seed.json
modules/The_Hidden_City_of_Numillian/seed_source_report.json
modules/The_Hidden_City_of_Numillian/source_fidelity_report.json
modules/The_Hidden_City_of_Numillian/accurate_ingest_benchmark_report.json
modules/The_Hidden_City_of_Numillian/validation_report.json
modules/The_Hidden_City_of_Numillian/toolkit_build_report.json
modules/The_Hidden_City_of_Numillian/MODULE_SUMMARY.md
modules/The_Hidden_City_of_Numillian/README.md
```

Runtime files remain ignored and are not publication artifacts:

```text
module_plot.json
party_tracker.json
areas/*.json except *_BU.json
encounters/**
player_quests_*.json
```

---

## Implementation Phases

### Phase 0: Stabilize GUI Defaults

Objective: Make the Module Builder GUI usable again while recovery work proceeds.

Tasks:

- Set `ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD = False` by default.
- Ensure accurate-ingest GUI jobs can still route through the existing ModuleBuilder path.
- Preserve source graph, optional fidelity diagnostics, and build-fidelity artifacts where available.
- Make job status clearly say when source-enhanced ModuleBuilder is used vs seed fallback.
- Add tests proving default GUI upload does not silently seed a skeletal module.

Acceptance:

- MD/PDF upload can build through ModuleBuilder.
- Deterministic seed writer is not invoked unless explicitly requested or test-injected.
- Existing readiness/finisher path still runs.

### Phase 1: Builder Handoff Audit

Objective: Map exactly what data ModuleBuilder and sub-generators need from accurate ingest.

Tasks:

- Audit `ModuleBuilder.build_module(...)`, `ModuleGenerator.generate_module(...)`, `AreaGenerator`, `LocationGenerator`, and `PlotGenerator` prompt inputs.
- Identify minimal prompt/context additions to preserve source rosters.
- Define `source_blueprint_context` serialization for current text-only entrypoint.
- Add tests that builder input contains required Numillian NPC/location/plot/puzzle names.

Acceptance:

- No generator rewrite required for first pass.
- The current `initial_concept` handoff can carry the source contract safely.

### Phase 2: Real LLM Blueprint Enrichment

Objective: Replace placeholder enrichment with bounded LLM extraction/enrichment.

Tasks:

- Implement pass-level LLM calls behind `ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT`.
- Use section-bounded source excerpts, not full-source monolithic prompts.
- Validate every returned patch against allowed fields and source refs.
- Persist enrichment reports with provider/model/cost/error metadata.
- Return `not_implemented`, `degraded`, or `failed` truthfully on no-op/provider failure.

Acceptance:

- Enabled enrichment applies real patches or reports honest non-completion.
- No structural fields can be mutated by enrichment.
- Numillian enrichment improves NPC/location/plot/puzzle detail without renaming source entities.

### Phase 3: Source-Enhanced ModuleBuilder Path

Objective: Feed enriched blueprint content to ModuleBuilder as the primary accurate-ingest build path.

Tasks:

- Serialize enriched blueprint into `builder_narrative.md` with source-lock sections.
- Persist `builder_input.json` showing handoff mode `source_enhanced_modulebuilder`.
- Modify packet builder routing so accurate-ingest ready blueprints call `_execute_module_builder(...)` by default.
- Ensure progress state says `building_with_modulebuilder`.
- Keep seed writer available only via explicit fallback/preview flag or helper call.

Acceptance:

- `ModuleBuilder.build_module(...)` remains the primary authoring call.
- Build result records source blueprint metadata.
- Build-fidelity gate runs after ModuleBuilder output.

### Phase 4: Generator-Level Source Lock Hardening

Objective: Reduce drift inside ModuleBuilder sub-generators.

Tasks:

- Add source-contract clauses to module, area, location, and plot prompts.
- Pass required rosters and source excerpts into relevant generator prompts where practical.
- Preserve source location names unless alias-approved.
- Preserve NPC names and roles unless source indicates ambiguity.
- Preserve puzzle setup/rules/solutions/failure consequences.
- Preserve plot topology and endings.

Acceptance:

- Build output preserves benchmark source names and required topology more reliably than narrative-only handoff.
- Drift becomes visible in fidelity reports instead of hidden in playable but inaccurate modules.

### Phase 5: Post-Build Fidelity Repair And Structural Finalization

Objective: Let Python repair structure and reports without rewriting adventure meaning.

Tasks:

- Run build-fidelity audit after ModuleBuilder output.
- Auto-repair safe structural issues: BU files, map files, coordinates, schema defaults, missing seed reports, report freshness.
- Do not auto-create replacement NPCs/plots/locations to satisfy source fidelity.
- Missing required source content remains blocker unless an explicit operator waiver is applied.
- Propagate source-fidelity status into module-level artifacts.

Acceptance:

- Structural repairs do not mask source omissions.
- Publishability gate sees final source-fidelity status.

### Phase 6: MODULE_SUMMARY Synthesis Reuse

Objective: Reuse summary traversal and LLM style safely for field enrichment and final markdown.

Tasks:

- Extract shared traversal/context helpers from `homebrewery_adventure_writer.py` where useful.
- Add source-aware narrative synthesis helpers for JSON patches.
- Keep markdown generation final-derived only.
- Add tests proving `MODULE_SUMMARY.md` cannot repair source-fidelity status.

Acceptance:

- NPC/location/plot prose can be enriched using shared context logic.
- Summary remains a publication artifact, not a source-fidelity input.

### Phase 7: Numillian End-To-End Proof

Objective: Prove the recovered architecture with the hardest known case.

Tasks:

- Rebuild Numillian from source markdown through source-enhanced ModuleBuilder path.
- Run benchmark and publishability gates.
- Compare source expectations to module output.
- Confirm v1 archive is non-production.
- Document any accepted limitations or waiver requirements.

Acceptance:

- Numillian preserves source locations, NPC threshold, puzzles, Gatepact/Kobe plot, and quirky tone.
- Publishability and source-fidelity reports agree.
- GUI flow can reproduce the path or an equivalent test-client flow.

---

## Testing Strategy

### Unit Tests

- Blueprint serialization includes required source rosters.
- Enrichment patch validation accepts only approved text fields.
- Enrichment status cannot report complete on no-op.
- Seed writer reports degraded/failed on missing required writes.
- Module summary remains derived-only.

### Integration Tests

- GUI route default path calls ModuleBuilder, not seed writer.
- Clean accurate-ingest builds proceed without mandatory review approval.
- Blocked or degraded source-fidelity states surface diagnostics and require explicit waiver only when the operator chooses to continue despite the blocker.
- Existing module overwrite requires confirmation.
- Build-fidelity blocked status prevents final publishability.
- Legacy modules without source artifacts remain source-fidelity `unknown` and fail open.

### Fixture Tests

- Numillian source expectations.
- One smaller Homebrewery module for faster regression.
- One PDF upload fixture if practical.

### Manual Smoke

- Upload markdown through GUI.
- Confirm clean source-fidelity diagnostics do not pause for approval.
- Build through ModuleBuilder.
- Confirm progress states are coherent.
- Confirm final module appears in module list.
- Download `MODULE_SUMMARY.md` from disk.

---

## OpenSpec Recovery Chain

This recovery is too large for one OpenSpec change. It should be delivered as a sequence of small, verified changes. GPT-5.5/Plan prepares each change and per-step builder prompts; the builder executes one step at a time; GPT-5.5 verifies the result before the next step.

Recommended chain: **10 OpenSpec changes**: one immediate stabilization change (`Change 0`) plus nine implementation/proof changes (`Change 1` through `Change 9`).

Do not archive the current `toolkit-accurate-ingest-gui-builder-unification` as-is. Either supersede it with this chain or revise it only after the recovery chain is green.

### Backstage Audit Assistant Integration

The backstage agentic harness work described in `plans/backstage-agents.md` should not be folded into the current Numillian NPC/location preservation slice. Accurate-ingest recovery should first finish the deterministic preservation chain already in progress:

- NPC preservation.
- Location preservation.
- Puzzle preservation regression repair.
- Benchmark and publishability reassessment.

After those gates are stable, add a separate read-only OpenSpec change:

```text
toolkit-accurate-ingest-backstage-audit-mvp
```

This first auditor should consume existing deterministic artifacts:

- `accurate_ingest_benchmark_report.json`
- `toolkit_build_report.json`
- `validation_report.json`
- `source_fidelity_report.json`
- `build_fidelity_report.json`
- Publishability audit JSON.

It should produce an evidence-backed blocker/regression summary and next-step recommendation, but MUST NOT:

- Mutate module artifacts.
- Weaken source-fidelity gates.
- Create waivers.
- Replace benchmark or publishability scripts.
- Become part of the live ModuleBuilder generation loop.

The existing ModuleBuilder LLM calls remain the creative authoring worker. The backstage audit and builder assistants should wrap and inspect that workflow rather than turn `ModuleBuilder` itself into an autonomous ReAct loop.

### Execution Discipline

For every change:

1. GPT-5.5 writes or revises the OpenSpec artifacts.
2. GPT-5.5 emits exactly one builder prompt for the next task using the `openspec-plan-to-builder` contract.
3. Builder executes only that task.
4. Builder reports files changed, commands run, and results.
5. GPT-5.5 verifies syntax, tests, scope, and behavior.
6. Only after PASS does GPT-5.5 emit the next builder prompt.

No builder step should combine unrelated phases. No step should require broad rewrites across the route, ModuleBuilder, generator prompts, and publication gates at the same time.

### Builder Prompt Rules

Each builder prompt should include:

- Step identifier.
- Allowed files.
- Forbidden files and forbidden behavior.
- MUST constraints from specs.
- SHOULD guidance from design.
- Exact verification commands.
- Required report format.
- Stop condition.

For large Python files, every prompt should include:

```text
Edit Strategy: Apply one anchored patch at a time, then run py_compile before the next patch. Do not use broad regex/script rewrites in indentation-sensitive files.
```

### Change 0: `toolkit-accurate-ingest-gui-stabilize-defaults`

Purpose: Make Module Builder GUI usable again immediately while recovery work proceeds.

Scope:

- Disable blueprint seed writer as default GUI authoring path.
- Route clean accurate-ingest GUI builds through existing ModuleBuilder path.
- Remove mandatory pre-build review/approval pauses from the default flow.
- Keep diagnostics and source-fidelity artifacts available.

Primary files:

- `model_config.py`
- `config_template.py`
- `web/extensions/toolkit_homebrew_packet_builder.py`
- `web/routes/toolkit_homebrew_routes.py`
- `web/templates/module_toolkit.html`
- Existing GUI flow tests.

Key MUSTs:

- Accurate-ingest GUI builds SHALL NOT call seed writer by default.
- Clean source-fidelity state SHALL NOT require user approval before build.
- Existing Describe-your-Adventure and packet build paths SHALL remain functional.
- Seed writer fallback SHALL require explicit flag or explicit route/request state.

Suggested tasks:

1. Add/normalize flags: `ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD=False`, `ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK=False`.
2. Update packet builder routing and tests so default accurate-ingest calls `_execute_module_builder(...)`.
3. Update GUI status copy to say diagnostics, not approval gate.
4. Verify upload/build route can progress without `awaiting_review` for clean builds.

Verification:

- `.venv/bin/python -m py_compile model_config.py web/extensions/toolkit_homebrew_packet_builder.py web/routes/toolkit_homebrew_routes.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity`
- Targeted source check: no default path invokes `_execute_seed_writer_build` without explicit fallback flag.

Exit gate:

- GUI ingest is usable again, even if source fidelity is not yet fully fixed.

### Change 1: `toolkit-accurate-ingest-entity-candidate-triage`

Purpose: Stop deterministic extraction from promoting narrative phrases into canonical entities.

Scope:

- Add candidate triage contract before candidates become NPCs/locations/items/monsters.
- Reject false positives like `but this is not true`.
- Preserve valid minor NPCs like Dog-Growl, Book-shut, and Deflation with location bindings.

Primary files:

- `utils/toolkit_source_extraction.py`
- `utils/toolkit_source_graph_synthesis.py`
- `utils/toolkit_builder_blueprint.py`
- `utils/toolkit_homebrew_normalizer.py`
- New or existing accurate-ingest tests.

Key MUSTs:

- Deterministic candidates SHALL NOT become canonical entities without adjudicated type.
- Narrative phrases SHALL be rejected or reclassified as plot/clue/tone notes, not NPCs.
- Kept NPCs SHALL include location, plot, faction, or explicit source-role binding.
- Triage decisions SHALL be persisted in an identity/triage report.

Suggested tasks:

1. Define triage schema and allowed adjudicated types.
2. Add deterministic prefilters for obvious narrative phrases without relying on prefilters alone.
3. Add LLM adjudication hook or cached classification seam for ambiguous candidates.
4. Wire triage decisions into blueprint generation.
5. Add Numillian regression for `but_this_is_not_true` rejection and Rookery Kenku preservation.

Verification:

- `.venv/bin/python -m py_compile utils/toolkit_source_extraction.py utils/toolkit_source_graph_synthesis.py utils/toolkit_builder_blueprint.py utils/toolkit_homebrew_normalizer.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_v2_contract`
- New triage test: false-positive phrase rejected, valid Kenku retained and bound to `The Rookery`.

Exit gate:

- Numillian blueprint no longer emits `but_this_is_not_true` as an NPC.

### Change 2: `toolkit-accurate-ingest-blueprint-enrichment-real-status`

Purpose: Make enrichment truthful and prepare real LLM patch passes.

Scope:

- Fix `utils/toolkit_blueprint_enrichment.py` so no-op enrichment cannot report complete.
- Add status semantics for disabled, not implemented, degraded, failed, and complete.
- Preserve current patch validator work.

Primary files:

- `utils/toolkit_blueprint_enrichment.py`
- `prompts/toolkit/blueprint_field_enrichment_prompt.txt`
- `scripts/test_toolkit_blueprint_enrichment_patches.py`

Key MUSTs:

- Disabled enrichment SHALL return `skipped`.
- Enabled but no provider orchestration SHALL return `not_implemented` or `degraded`, not `complete`.
- Provider failure SHALL preserve seeded/builder content and report degraded/failed.
- Structural mutation patches SHALL be rejected.

Suggested tasks:

1. Normalize enrichment status constants and report shape.
2. Add tests for disabled/no-op/provider-failure statuses.
3. Add prompt contract placeholders for later real passes.
4. Ensure packet builder treats enrichment as non-blocking unless structural mutation is attempted.

Verification:

- `.venv/bin/python -m py_compile utils/toolkit_blueprint_enrichment.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_enrichment_patches`

Exit gate:

- Enrichment status is honest and cannot mask missing implementation.

### Change 3: `toolkit-accurate-ingest-llm-blueprint-enrichment`

Purpose: Implement bounded LLM extraction/enrichment into blueprint facts before ModuleBuilder handoff.

Scope:

- Add real small-pass LLM calls for NPCs, locations, plots, puzzles/clues, encounters/items, and tone.
- Cache or hash by source chunk where practical.
- Apply only validated patches to blueprint fields.

Primary files:

- `utils/toolkit_blueprint_enrichment.py`
- `prompts/toolkit/blueprint_field_enrichment_prompt.txt`
- `utils/toolkit_homebrew_upload_contract.py` if artifact contract needs expansion.
- Enrichment tests and fixture data.

Key MUSTs:

- Enrichment SHALL use bounded source excerpts, not full-source monolithic prompts.
- LLM output SHALL be JSON-only and validated before application.
- LLM SHALL NOT rename source entities, change IDs, alter connectivity, rewrite puzzle rules, or invent major plotlines.
- Applied patches SHALL carry source refs or source-derived justification.
- All provider failures SHALL fail open/degrade without corrupting blueprint artifacts.

Suggested tasks:

1. Implement one pass first: NPC enrichment.
2. Verify with Numillian Rookery NPCs and `but this is not true` rejection.
3. Add location pass.
4. Add plot/puzzle/clue pass.
5. Add encounter/item/tone pass.
6. Add cost/caching telemetry.

Verification:

- `.venv/bin/python -m py_compile utils/toolkit_blueprint_enrichment.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_enrichment_patches`
- Fixture test using local source excerpts without live provider where possible.
- Optional provider smoke only when explicitly enabled.

Exit gate:

- Enriched blueprint has materially better NPC/location/plot fields than deterministic extraction alone.

### Change 4: `toolkit-accurate-ingest-modulebuilder-handoff`

Purpose: Feed enriched source blueprint into the existing ModuleBuilder orchestration as the default accurate-ingest authoring path.

Scope:

- Build a source-enhanced `builder_narrative.md` or `builder_input.json` consumed by `_execute_module_builder(...)`.
- Keep `ModuleBuilder.build_module(...)` as the creative authoring call.
- Record handoff metadata and source locks.

Primary files:

- `web/extensions/toolkit_homebrew_packet_builder.py`
- `utils/toolkit_builder_blueprint.py`
- `core/generators/module_builder.py` only if a typed optional argument is truly needed.
- Handoff tests.

Key MUSTs:

- Accurate-ingest default authoring path SHALL call ModuleBuilder.
- Handoff SHALL include required NPC/location/plot/puzzle/encounter/tone sections.
- Handoff SHALL include forbidden invention/replacement rules.
- Legacy concept-builder flow SHALL remain compatible.

Suggested tasks:

1. Add source-enhanced handoff serializer.
2. Persist `builder_input.json` and `builder_narrative.md` artifacts.
3. Route accurate-ingest packet build through `_execute_module_builder(...)` with source-enhanced narrative.
4. Add tests proving required Numillian names appear in the handoff.
5. Add tests proving default path does not seed.

Verification:

- `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py utils/toolkit_builder_blueprint.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_v2_contract`

Exit gate:

- Accurate-ingest GUI build uses source-enhanced ModuleBuilder by default.

### Change 5: `toolkit-accurate-ingest-generator-source-locks`

Purpose: Harden ModuleBuilder sub-generator prompts against source drift.

Scope:

- Add source-lock prompt guidance to module, area, location, and plot generation.
- Prefer minimal generator code changes; first pass can be prompt/context only.

Primary files:

- `core/generators/module_generator.py`
- `core/generators/area_generator.py`
- `core/generators/location_generator.py`
- `core/generators/plot_generator.py`
- `prompts/generators/*` if applicable.
- Generator source-contract tests.

Key MUSTs:

- Generators SHALL preserve required source names and roles when provided.
- Generators SHALL NOT replace source plot topology with unrelated defaults.
- Generators SHALL report or preserve unresolved required elements instead of silently replacing them.
- Single-player/upstream-style concept generation SHALL remain functional when no source blueprint is present.

Suggested tasks:

1. Add context wording for source-roster preservation.
2. Add optional source blueprint context to generator prompts where practical.
3. Add source-contract tests checking prompt includes source-lock clauses.
4. Add smoke test with small fixture handoff.

Verification:

- `.venv/bin/python -m py_compile core/generators/module_generator.py core/generators/area_generator.py core/generators/location_generator.py core/generators/plot_generator.py`
- Source-contract tests for prompt clauses.
- Existing module builder tests, if available.

Exit gate:

- Generator prompts no longer treat source-enhanced builds as generic blank-concept generation.

### Change 6: `toolkit-accurate-ingest-monster-encounter-materialization`

Purpose: Convert source monster references and encounter seeds into module-local monster artifacts and encounter-plan bindings without replacing ModuleBuilder.

Scope:

- Materialize source monster references from source-enhanced accurate-ingest artifacts into `monsters/*.json` or explicit unresolved blockers.
- Bind encounter seed references to canonical source monster identities before post-build reports run.
- Preserve ModuleBuilder as the creative authoring path and use Python only for reuse-first stat artifact closure.
- Keep deterministic seed writer in support role only.

Primary files:

- `web/extensions/toolkit_homebrew_packet_builder.py`
- `utils/module_monster_authority.py` or a new accurate-ingest monster helper if needed.
- `utils/toolkit_build_fidelity.py` if report consumption needs narrow expansion.
- `scripts/rebuild_numillian_accurate_ingest.py` only for test-harness wiring, not production rebuild by default.
- Accurate-ingest GUI, blueprint, and Numillian test suites.

Key MUSTs:

- Source monster references SHALL be materialized by reuse-first resolution or reported as explicit unresolved blockers.
- Encounter seeds SHALL retain monster bindings when source monster refs are present and unambiguous.
- The implementation SHALL NOT invent replacement monsters to satisfy counts.
- NPC/source-character names SHALL NOT be converted into monster artifacts unless source evidence marks them as monsters or combatants.
- Legacy concept builds and non-source accurate-ingest paths SHALL remain compatible.
- Tests SHALL be provider-free and SHALL NOT require a production Numillian rebuild.

Suggested tasks:

1. Add provider-free tests proving source monster refs and encounter seeds reach the materialization helper.
2. Add reuse-first monster materialization for existing SRD/module/bestiary-compatible monster names.
3. Add unresolved-blocker reporting for unmatched source monster refs.
4. Bind encounter seeds to canonical monster refs where source refs are unambiguous.
5. Verify legacy/no-source paths do not emit monster materialization artifacts.

Verification:

- `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py utils/module_monster_authority.py utils/toolkit_build_fidelity.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow scripts.test_toolkit_blueprint_v2_contract`
- `.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_benchmark scripts.test_accurate_ingest_numillian_end_to_end`

Exit gate:

- Source monster refs and encounter seeds no longer disappear between source-enhanced handoff and module artifact/report generation.

### Change 7: `toolkit-accurate-ingest-source-fidelity-publication-propagation`

Purpose: Ensure final module publishability consumes accurate source-fidelity status.

Scope:

- Propagate workspace source-fidelity results into module-level artifacts.
- Ensure `toolkit_build_report.json`, benchmark report, and publishability audit agree.

Primary files:

- `web/extensions/toolkit_homebrew_packet_builder.py`
- `web/extensions/toolkit_module_finisher.py`
- `utils/toolkit_build_fidelity.py`
- `scripts/audit_module_publishability.py`
- Publication/report tests.

Key MUSTs:

- Accurate-ingest modules SHALL carry final source-fidelity status into module artifacts.
- Publishability SHALL block on source-fidelity blocked status.
- Legacy modules without accurate-ingest artifacts SHALL remain `unknown` and fail open.
- `MODULE_SUMMARY.md` SHALL NOT alter source-fidelity status.

Suggested tasks:

1. Define module-level source-fidelity artifact precedence.
2. Copy or summarize workspace fidelity into module directory after build.
3. Update toolkit report composition.
4. Update publishability audit consumption.
5. Add tests for blocked/degraded/pass/unknown.

Verification:

- `.venv/bin/python -m py_compile web/extensions/toolkit_module_finisher.py scripts/audit_module_publishability.py utils/toolkit_build_fidelity.py`
- `.venv/bin/python -m unittest -q scripts.test_audit_module_publishability`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_module_summary_finisher_contract`

Exit gate:

- Final publishability cannot ignore accurate-ingest source-fidelity blockers.

### Change 8: `toolkit-accurate-ingest-summary-synthesis-derived-only`

Purpose: Reuse summary traversal and LLM style safely without letting summaries repair fidelity.

Scope:

- Extract reusable narrative synthesis helpers if useful.
- Keep `MODULE_SUMMARY.md` final-derived.
- Optionally use shared context builders for JSON patch enrichment.

Primary files:

- `utils/homebrewery_adventure_writer.py`
- New optional `utils/module_narrative_synthesis.py`
- `web/extensions/toolkit_module_finisher.py`
- Summary tests.

Key MUSTs:

- `MODULE_SUMMARY.md` SHALL be generated from final module JSON.
- Summary generation SHALL NOT mutate module JSON.
- Summary content SHALL NOT be used as source-fidelity repair input.
- Summary failure SHALL degrade report status but not corrupt module artifacts.

Suggested tasks:

1. Identify reusable traversal helpers.
2. Extract only if it reduces duplication; do not churn working summary generation unnecessarily.
3. Add tests proving summary is derived-only.
4. Keep disk-first download behavior.

Verification:

- `.venv/bin/python -m py_compile utils/homebrewery_adventure_writer.py web/extensions/toolkit_module_finisher.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_module_summary_finisher_contract`
- `.venv/bin/python -m unittest -q scripts.test_homebrewery_adventure_writer`

Exit gate:

- Summary remains publication output, not source-fidelity machinery.

### Change 9: `toolkit-accurate-ingest-numillian-release-proof`

Purpose: Prove the full recovered pipeline on Numillian and release-ready module workflows.

Scope:

- Rebuild or refresh `modules/The_Hidden_City_of_Numillian/` from source markdown.
- Verify benchmark, validation, publishability, summary, and GUI-equivalent flow.
- Confirm historical v1 archive is non-production.

Primary files:

- `modules/The_Hidden_City_of_Numillian/**`
- `data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json` only if benchmark expectations need correction.
- `scripts/test_accurate_ingest_numillian_end_to_end.py`
- `scripts/benchmark_accurate_ingest.py`
- Potential docs/report artifacts.

Key MUSTs:

- Production Numillian SHALL preserve source locations, NPC threshold, puzzle chain, Gatepact/Kobe plot, and quirky tone.
- `but_this_is_not_true` SHALL NOT appear as an NPC.
- Dog-Growl, Book-shut, and Deflation SHALL be preserved as Rookery-bound source NPCs if benchmark/source expectations require them.
- Runtime files SHALL remain ignored and not required for publication.
- No `git add -f` SHALL be needed for canonical artifacts.

Suggested tasks:

1. Run source-enhanced build into temp workspace.
2. Compare output with production target.
3. Replace/repair production target only from verified output.
4. Run validation and benchmark.
5. Run publishability audit.
6. Run GUI-equivalent route test.
7. Document final source-fidelity result and any accepted limitations.

Verification:

- `.venv/bin/python core/validation/validate_module_files.py --module The_Hidden_City_of_Numillian`
- `.venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json`
- `.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json`
- `.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_end_to_end`
- `openspec validate toolkit-accurate-ingest-numillian-release-proof`

Exit gate:

- Numillian is release/gametest-ready or blockers are explicit, narrow, and reviewable.

---

## Next OpenSpec Builder Handoff (2026-05-26)

### Current Disposition

The previous Numillian source-fidelity blocker chain, source-enhanced ModuleBuilder handoff, read-only backstage audit MVP, builder-audit briefing, and generator source-lock slice are complete and archived.

Current source-fidelity state:

- `source_fidelity_status`: `pass`
- `npc_preservation`: `pass`, `23/23`
- `location_preservation`: `pass`, `13/13`
- `puzzle_preservation`: `pass`, `3/3`
- `lore_preservation`: `pass`, `2/2`
- `tone_preservation`: `pass`
- Source monster refs and encounter seeds are now visible in source-enhanced `builder_input` and ModuleBuilder source context.
- Active OpenSpec changes: none.
- Dirty Numillian module artifacts remain intentionally uncommitted until the user explicitly requests module publication.

Completed background changes:

- `toolkit-accurate-ingest-llm-blueprint-enrichment` is archived background work.
- `toolkit-accurate-ingest-numillian-source-fidelity-fix` is archived background work.
- `toolkit-accurate-ingest-numillian-npc-location-preservation` is archived background work and restored Numillian benchmark source fidelity to pass.
- `toolkit-accurate-ingest-modulebuilder-handoff` is archived background work and restored the default accurate-ingest GUI route to source-enhanced ModuleBuilder handoff with explicit seed-writer support modes.
- `toolkit-accurate-ingest-backstage-audit-mvp` is archived background work and provides a read-only audit artifact set: `run.json`, `evidence.json`, `audit_report.json`, and `recommendation.json` under `data/agent_runs/accurate_ingest_audit/<task_id>/`.
- `toolkit-accurate-ingest-builder-audit-briefing` is archived background work and produces compact builder-facing audit briefs.
- `toolkit-accurate-ingest-generator-source-locks` is archived background work and propagates source locks plus monster/encounter source fields into generator prompt context.

### How The LLM Builder Should Use Backstage Audits

Backstage audits should become the LLM Builder's diagnostic briefing layer, not another authoring engine.

The safe pattern is:

```text
Backstage audit run artifacts
  -> deterministic builder briefing
  -> OpenSpec/patch proposal prompt context
  -> human/plan verification
  -> one narrow builder task
```

An LLM Builder can use audit outputs to:

- See which deterministic gate is failing without rereading the whole module.
- Distinguish real source-fidelity blockers from stale toolkit/report disagreements.
- Select the next work lane: report refresh, artifact repair, OpenSpec design, or no action.
- Cite evidence references in its patch proposal instead of relying on vague narrative summaries.
- Avoid touching module artifacts when the audit only says reports disagree.

An LLM Builder must not use audit outputs to:

- Override benchmark, validation, readiness, or publishability gates.
- Treat `recommendation.json` as authorization to mutate files.
- Enter the live ModuleBuilder generation loop.
- Create waivers or weaken source-fidelity gates.
- Rewrite module content directly from a report summary.

### Next Change To Scaffold

Create the next focused OpenSpec change:

```text
toolkit-accurate-ingest-monster-encounter-materialization
```

This change turns the now-visible source monster references and encounter seeds into deterministic module artifact/report contracts before any production Numillian rebuild.

Purpose:

- Materialize source monster references into module-local `monsters/*.json` artifacts when reuse-first resolution can identify a valid monster.
- Preserve unresolved source monster refs as explicit blockers instead of silently dropping them.
- Bind encounter seeds/encounter plans to canonical source monster identities when unambiguous.
- Report planned, generated, reused, and unresolved monster/encounter counts deterministically.
- Preserve legacy concept builds and no-source accurate-ingest paths.

### Required Capabilities

The OpenSpec scaffold SHOULD include these capability specs:

1. `accurate-ingest-source-monster-materialization`
2. `accurate-ingest-encounter-plan-monster-binding`
3. `accurate-ingest-monster-materialization-reporting`
4. `accurate-ingest-monster-materialization-compatibility`

### MUST Contract For The Change

- Source monster references SHALL be materialized by reuse-first resolution or recorded as explicit unresolved blockers.
- Encounter seeds SHALL retain source monster bindings when refs are present and unambiguous.
- The implementation SHALL NOT invent replacement monsters, weaken benchmark thresholds, or change scanner logic.
- NPC/source-character names SHALL NOT be materialized as monster artifacts unless source evidence marks them as monsters or combatants.
- Legacy concept builds and accurate-ingest jobs with no source monster refs SHALL remain compatible and SHALL NOT emit false blocker reports.
- Tests SHALL be provider-free and SHALL NOT require a production Numillian rebuild.

### SHOULD Guidance

- Prefer a small helper around existing monster authority/hydration utilities before introducing new builder architecture.
- Start with tests around source refs, encounter seeds, and reporting shape before broad materialization behavior.
- Use temp module/workspace fixtures where possible; keep production Numillian artifact mutation out of this scaffold.
- Reuse existing monster schemas/templates and validation helpers instead of hand-writing large stat blocks.
- Treat MMG/media generation as later work.

### Initial Builder Prompt

See `openspec/changes/toolkit-accurate-ingest-monster-encounter-materialization/builder_prompts.md` for the Step 1.1 full-variant builder prompt.

### Chain-Level Archive Policy

Archive changes only after their verification gate passes and the next dependent change has not discovered a contradiction.

Recommended archive grouping:

- Archive Change 0 immediately after GUI usability is restored.
- Archive Changes 1-3 only after enriched blueprint output is proven on fixtures.
- Archive Changes 4-6 only after ModuleBuilder handoff and seed support roles are stable.
- Archive Changes 7-8 after final report/summary semantics are stable.
- Archive Change 9 last, as the release proof.

### Plan-To-Builder Step Template

Use this template for every builder step:

```text
Implement OpenSpec <change> Step <N.M> only.

Goal: <one sentence>
Allowed: <exact file list>
Forbidden: <scope exclusions>
Required MUSTs:
- <testable invariant>
- <testable invariant>
SHOULD guidance:
- <preferred approach>
Edit Strategy: Apply one anchored patch at a time, then run py_compile before the next patch. Do not use broad regex/script rewrites in indentation-sensitive files.
Verify:
- <compile command>
- <targeted test command>
Report:
- Files changed
- Commands run
- Test results
- Any blockers or deviations
Stop: Do not start the next task.
```

---

## Immediate Code Decisions For Review

These are proposed decisions, not yet implementation instructions:

1. Revert default flag:

```python
ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD = False
```

2. Add a separate explicit flag for support/fallback use:

```python
ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK = False
```

3. Rename build mode values:

```text
source_enhanced_modulebuilder
blueprint_seed_preview
blueprint_seed_fallback
legacy_concept_modulebuilder
```

4. Keep existing `_execute_module_builder(...)` as the normal executor.

5. Keep `_execute_seed_writer_build(...)`, but require explicit fallback/preview routing.

6. Implement real enrichment before turning enrichment on by default.

7. Treat current `toolkit-accurate-ingest-gui-builder-unification` as complete-but-not-archiveable until superseded or corrected.

---

## Risks And Mitigations

| Risk | Mitigation |
|---|---|
| ModuleBuilder still invents content despite source contract | Build-fidelity blockers, stronger generator prompt contracts, required source rosters, benchmark tests. |
| LLM enrichment becomes another monolithic overlarge prompt | Section-bounded passes and cached per-section extraction. |
| Seed writer work is wasted | Reclassify as preview/fallback/fixture/comparator/repair helper. |
| GUI becomes confusing | One visible state machine and explicit build mode labels. |
| Summary hides missing source truth | Keep summary derived-only and excluded from source-fidelity repair. |
| Cost increases | Cache section extraction and enrichment by content hash; use smaller passes; run benchmarks deterministically. |
| Existing module publication work regresses | Keep readiness/media/semantic/publishability gates unchanged as final pipeline. |

---

## Success Criteria

The recovery is successful when:

1. GUI ingest is usable again for `.md` and `.pdf` uploads.
2. Accurate-ingest default build path uses the existing ModuleBuilder orchestration with source-enhanced input.
3. Deterministic seed writer remains available but no longer silently replaces ModuleBuilder.
4. LLM enrichment is either real and bounded or honestly reported as unavailable.
5. Numillian source benchmark passes or reports explicit reviewable limitations.
6. Final publishability status includes source-fidelity status for accurate-ingest modules.
7. `MODULE_SUMMARY.md` is generated from final audited module data and cannot repair fidelity failures.
8. Existing modules and legacy concept-builder workflows remain functional.

---

## Working Principle

The builder formats the adventure. It must not replace it.

Python preserves and verifies source truth. The LLM interprets and writes within evidence bounds. ModuleBuilder remains the creative engine, now supplied with the structured source truth it lacked.
