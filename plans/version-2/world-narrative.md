# World Narrative Plan v0.4

Status: Planning in progress
Date: 2026-06-28
Owner: Narrative systems + memory integration
Track reference: `plans/version-2/v2-narrative-track.md`

Related plans:

- `plans/version-2/module-import.md` = scaled canonical module-import lane
- `plans/version-2/memory.md` = retrieval/storage contracts
- `plans/version-2/titan-integration.md` = later interpreted-state consumer

## Seed DB

The world narrative system operates on a pre-built data artifact: `data/world_narrative_seed.db`. This is a read-only SQLite database committed to the repository that provides D&D alignment profiles, mythic conflict templates, cosmological domain catalogs, and motif/archetype/faction patterns for use by runtime retrieval, the campaign world model, and module builder integration.

## Current Baseline

### Storage

- `data/world_narrative_seed.db` — committable data artifact. Serves as the install baseline.
- `data/memory.db` — runtime working DB (gitignored). Merges seed tables with runtime tables.
- Bootstrap: on first run, if `data/memory.db` is missing, the runtime merges seed DB tables.

### Runtime tables (NEQ-TTRPG owns these)

`core/memory/memory_db.py` holds the runtime schema. The world-narrative seed tables (`inspiration_*`, `atom_*`, `alignment_*`, `cosmological_*`, `mythic_*`, `deity_*`, `campaign_*`) are verified at bootstrap from the seed DB. Runtime-only tables (`memory_events`, `entities`, `journal_entries`, `companion_memory_state`, `narrative_threads`, etc.) are created by NEQ migrations.

### Schema (seed DB tables)

#### Core data

`inspiration_profiles`, `inspiration_atoms`, `atom_relations`, `atom_statistics` — motif, archetype, faction, and tone patterns for narrative interpretation.

#### D&D alignment

`alignment_profiles` — continuous ethical/moral/balance scores with 5e classic labels for entities, factions, atoms, and deities.

#### Cosmological domains

`cosmological_domains` — planar realms, demiplanes, elemental planes with alignment affinity and SRD references.

#### Mythic conflicts

`mythic_conflicts` — the great multiverse tensions (Law vs Chaos, Nature vs Civilization, Fate vs Free Will, etc.) with narrative pattern templates and alignment mappings.

`conflict_alignments` — bridges entities/atoms to conflicts with alignment strength.

#### Deity archetypes

`deity_archetypes` — god-like patterns (Trickster, War God, Harvest Goddess, Death God, etc.) with divine domains and narrative roles.

`deity_manifestations` — entity-to-archetype mappings.

#### Campaign world model

`campaign_world_model` — versioned campaign-specific worldview snapshots.

`campaign_world_delta` — proposed worldview updates with apply lifecycle.

#### Narrative threads

`narrative_threads`, `narrative_thread_events`, `narrative_actor_state`, `module_narrative_seeds` — campaign-facing continuity state. These are seed DB tables that NEQ-TTRPG may also extend at runtime.

## Storage Model

- Extend `data/memory.db` for narrative state — seed tables + runtime tables in one DB.
- Tracked baseline: `data/world_narrative_seed.db` (committed).
- Runtime/bootstrap policy:
  1. `data/world_narrative_seed.db` is the install baseline.
  2. Runtime working DB remains `data/memory.db` (gitignored).
  3. First-run bootstrap: if `data/memory.db` is missing, merge seed DB tables.
  4. Runtime DB diverges from seed immediately (user campaign data appended).

## Integration Hooks (current codebase)

Canon event ingestion:

- `updates/plot_update.py` -> thread progression
- `core/ai/action_handler.py` -> transition/faction pressure events
- `core/managers/combat_manager.py` -> consequence events
- `core/managers/location_manager.py` -> location consequence transitions

Retrieval injection:

- `main.py` -> bounded `NARRATIVE PRESSURE` block in DM note path
- `core/managers/campaign_manager.py` -> cross-module continuity pack
- `core/generators/module_builder.py` -> continuity seed preamble
- `core/generators/module_stitcher.py` -> write back module narrative seeds

## Retrieval Contracts (bounded)

Turn-time pack:

- `get_narrative_turn_pack(module_name, location_id, active_entities, max_items=6)`
- output: `threats`, `obligations`, `continuity`

Transition pack:

- `get_transition_pressure_pack(from_module, to_module, max_items=6)`

Builder pack:

- `get_module_seed_pack(target_module, max_items=10)`

Ordering: priority desc -> recency desc -> stable id asc

### World picture lifecycle (interpreted, not hardwired)

At campaign start:

1. Bootstrap LLM composes a `campaign_world_model` from:
   - merged global inspiration atoms
   - atom relations and statistics
   - alignment profiles and mythic conflicts
   - selected module/campaign setup context
2. Result is a campaign-specific worldview snapshot (version 1).

During campaign play:

1. New canon events land in memory/thread tables.
2. Ratio LLM proposes worldview updates as `campaign_world_delta`.
3. Approved deltas are applied to create next `campaign_world_model` version.

Outcome: Campaigns remain family-similar (same inspiration prior) but relationship maps shift per playthrough.

### LLM entry point contract #1 - EGO/Ratio drift and strategy

- Inputs: current `campaign_world_model`, recent memory events/links, active threads, actor state, recent narrator outputs.
- Outputs: drift report, proposed `campaign_world_delta`, optional actor-state updates.
- Writes: interpreted narrative state only. Never mechanical truth.

### LLM entry point contract #2 - Module Builder interpretation

- Inputs: latest `campaign_world_model`, active high-priority threads, actor-state pressures, module registry.
- Outputs: seeded narrative structure, `module_narrative_seeds`, candidate thread continuations.
- Writes: narrative seeds and proposed continuations. Never event history.

### LLM entry point contract #3 - Narrator runtime interpretation

- Inputs: player inputs (highest signal), bounded pressure pack, DM note mechanical truth, SRD constraints.
- Outputs: narrative response, action proposals.
- Writes: none directly. Emits events that Python converts into canonical updates.

### Permission model

- Facts (append-only/audited): event history, mechanical outcomes, validated action results.
- Interpretation (versioned/revisable): worldview summary, projected tensions, likely allegiances.
- Facts cannot be silently rewritten.

## Rollout Plan

Phase 1 - Foundation

- Verify world-narrative seed tables exist in runtime DB after bootstrap.
- Add `core/memory/narrative_state.py` for retrieval helpers.
- Add runtime bootstrap: copy/merge seed DB tables when `data/memory.db` is missing.

Phase 2 - World model bootstrap and Ratio loop

- Implement campaign-start world model bootstrap (`campaign_world_model` v1).
- Implement Ratio drift check loop and delta proposal/apply flow.

Phase 3 - Hook integration

- Wire plot/combat/transition hooks.
- Feed canonical events into thread and actor-state updates.

Phase 4 - Prompt and builder integration

- Inject pressure packs into DM note and module builder.
- Ensure narrator sees bounded interpreted world pressure, not raw DB dumps.

Phase 5 - Safety gates

- Verify runtime DB never writes back to seed DB.

## Verification Checklist

Automated:

1. Seed DB bootstrap creates runtime tables correctly on fresh install.
2. Thread lifecycle correctness.
3. Retrieval ordering stability across alignment/mythic tables.
4. Save/export/import parity with world-narrative tables.
5. Ratio drift loop writes only interpreted state, never mechanical fields.
6. Distribution checks confirm seed DB is present and valid.

Manual:

1. Start campaign from seed DB and verify world model generates.
2. Start two campaigns from same seed DB and verify world models are similar but not identical.
3. Confirm campaign continuity works across modules with world-narrative pressure.
