# Tasks

## 1. NPC Enrichment Pass

- [x] 1.1 Add an NPC enrichment pass scaffold that selects bounded source excerpts and kept/reclassified candidate records without calling a live provider in default tests.
- [x] 1.2 Add a strict JSON response parser/converter for NPC enrichment output into validated enrichment patch candidates.
- [x] 1.3 Apply only validator-approved NPC prose/source-context patches and preserve status/report diagnostics for applied, rejected, and invalid patches.

## 2. Numillian NPC Fixture Regressions

- [x] 2.1 Add fixture coverage proving `but this is not true` is not promoted into NPC/module actor output by enrichment.
- [x] 2.2 Add fixture coverage proving Dog-Growl, Book-shut, and Deflation can be enriched as kept NPCs with The Rookery binding and source refs.
- [x] 2.3 Add no-live-provider tests for provider timeout/error, invalid JSON, and unsafe structural patch proposals.

## 3. Location Enrichment Pass

- [x] 3.1 Add location pass scaffolding for bounded keyed-location excerpts.
- [x] 3.2 Allow safe prose/location-detail patches for description, DM instructions, features, clues, traps, DC checks, doors, loot, NPCs, monsters, and plot hooks.
- [x] 3.3 Add fixture tests proving structural location fields such as IDs, names, coordinates, and connectivity remain immutable.

## 4. Plot, Puzzle, Clue, Encounter, Item, And Tone Passes

- [x] 4.1 Add plot/puzzle/clue enrichment scaffolds for descriptions, triggers, outcomes, dependency explanations, failure states, endings, clues, setup, rules summaries, and solution text without changing source structure.
- [x] 4.2 Add encounter/item enrichment scaffolds for encounter purpose, avoidability, social/combat path, monster purpose, item role, and source refs.
- [x] 4.3 Add tone/style pass output for ModuleBuilder guidance only, with tests proving it does not invent plot content.

## 5. Cache, Telemetry, And Artifact Contract

- [x] 5.1 Add deterministic input hashing/cache keys for pass inputs where practical.
- [x] 5.2 Add pass telemetry for provider call count, cache hits/misses, parse failures, rejected patch count, applied patch count, and status.
- [x] 5.3 Expand artifact/report contract only as needed to surface enrichment pass metadata without breaking existing consumers.

## 6. Verification

- [x] 6.1 Run compile checks for modified Python files.
- [x] 6.2 Run targeted blueprint enrichment tests.
- [x] 6.3 Run accurate-ingest blueprint/entity-triage regression tests.
- [x] 6.4 Run relevant toolkit GUI/build parity tests.
- [x] 6.5 Validate the OpenSpec change.

## Suggested Verification Commands

```bash
.venv/bin/python -m py_compile utils/toolkit_blueprint_enrichment.py scripts/test_toolkit_blueprint_enrichment_patches.py
.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_enrichment_patches
.venv/bin/python -m unittest -q scripts.test_toolkit_entity_candidate_triage scripts.test_toolkit_blueprint_v2_contract
.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity
openspec validate toolkit-accurate-ingest-llm-blueprint-enrichment
```
