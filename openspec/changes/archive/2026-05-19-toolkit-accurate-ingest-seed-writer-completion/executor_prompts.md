# Executor Prompts: Accurate-Ingest Seed Writer Completion

## Deepseek V4 Flash Builder Prompt - Full Step-By-Step

Implement OpenSpec change `toolkit-accurate-ingest-seed-writer-completion` only.

### Goal

Complete the deterministic accurate-ingest seed writer so uploaded adventure source truth becomes a complete provider-free NEQ module seed before any LLM enrichment can run.

### Allowed Files

Primary:

- `utils/toolkit_blueprint_seed_writer.py`
- `scripts/test_toolkit_blueprint_seed_writer.py`

OpenSpec/task docs may be updated only to mark completed tasks after verification:

- `openspec/changes/toolkit-accurate-ingest-seed-writer-completion/tasks.md`

Forbidden unless explicitly needed and justified in the report:

- GUI routes
- packet builder routing
- finisher
- publishability audit
- module data under `modules/`

### Hard Contract

- MUST NOT call LLM providers.
- MUST preserve existing public helper `materialize_module_from_blueprint(...)`.
- MUST preserve existing blocked/non-v2/directory-exists refusal behavior.
- MUST emit `npcs_seed.json`, `monsters_seed.json`, and `seed_source_report.json` for non-dry-run successful blueprint-native seeding.
- MUST include those artifacts in dry-run planned files.
- MUST not return `seed_status: success` if a required canonical artifact failed to write.
- MUST preserve source names and source order from the blueprint before enrichment.
- MUST keep edits small and anchored. Apply one logical patch at a time.

### Implementation Steps

1. Read current `utils/toolkit_blueprint_seed_writer.py` and identify existing helpers for slugging, planned files, module context, plot, area, map, write tracking, and warnings.
2. Add constants near existing status/version constants:
   - `NPC_SEED_VERSION = "toolkit_npc_seed.v1"`
   - `MONSTER_SEED_VERSION = "toolkit_monster_seed.v1"`
   - `SEED_SOURCE_REPORT_VERSION = "toolkit_seed_source_report.v1"`
3. Add `_build_npcs_seed(blueprint, npc_roster)`:
   - Use `npc_roster` entries.
   - Preserve `display_name`, `aliases`, `role`, `faction`, `location_binding`, `scene_presence`, `criticality`, and `source_refs` if present.
   - Return schema version, source, blueprint version, module title/source hash if available, and `npcs` list.
4. Add `_build_monsters_seed(blueprint, location_roster, encounter_plan)`:
   - Preserve explicit monster/creature names from `encounter_plan` and structured location hints where available.
   - Do not create monster stat files.
   - Include conservative `materialization_hint` values such as `custom_needed`, `srd_lookup_candidate`, or `source_reference`.
   - Deduplicate by normalized name while preserving first source order.
5. Add `_build_seed_source_report(blueprint, area_plan, location_roster, npc_roster, plot_graph, puzzle_graph, clue_graph, encounter_plan, item_roster)`:
   - Include report version, source hash, module title, and arrays for locations, NPCs, plot beats, puzzles, clues, encounters, and items.
   - Preserve atom/blueprint IDs, source order index, original display names, criticality, and source refs.
6. Update planned file computation to include:
   - `npcs_seed.json`
   - `monsters_seed.json`
   - `seed_source_report.json`
7. Write the three new artifacts in `materialize_module_from_blueprint(...)` after core context/plot/area/map generation.
8. Add required artifact classification:
   - Required: core context/plot, at least one area for non-empty blueprints, map files generated from area maps, and the three new seed/report artifacts.
   - If `_safe_write_json` records any required artifact as skipped/failed, return a non-success seed status with blockers.
   - Keep optional failures as warnings/degraded if you add optional classes.
9. Update tests in `scripts/test_toolkit_blueprint_seed_writer.py`:
   - Assert non-dry-run creates `npcs_seed.json` and includes sample NPC names.
   - Assert non-dry-run creates `monsters_seed.json` when fixture has encounter/monster hints.
   - Assert dry-run planned files include all three new artifacts and writes nothing.
   - Assert Numillian-like fixture source order is represented in `seed_source_report.json`.
   - Add a write-failure test by patching the writer helper or write function; required write failure must not return success.
   - Preserve existing tests.
10. Run verification commands. Fix failures with minimal patches.
11. Mark completed tasks in `tasks.md` only after verification passes.

### Edit Strategy

Apply one anchored patch at a time, then run:

```bash
.venv/bin/python -m py_compile utils/toolkit_blueprint_seed_writer.py
```

After tests are updated, run the full gate below.

### Verification Gate

```bash
.venv/bin/python -m py_compile utils/toolkit_blueprint_seed_writer.py scripts/test_toolkit_blueprint_seed_writer.py
.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_seed_writer
openspec validate toolkit-accurate-ingest-seed-writer-completion
python3 scripts/check_ascii_compliance.py --summary-only utils/toolkit_blueprint_seed_writer.py scripts/test_toolkit_blueprint_seed_writer.py
```

### Report Back

Return only:

- Files changed.
- Summary of artifact shapes added.
- Test/validation command results.
- Any blockers or intentionally deferred items.

Do not commit. Do not push. Do not edit module data.
