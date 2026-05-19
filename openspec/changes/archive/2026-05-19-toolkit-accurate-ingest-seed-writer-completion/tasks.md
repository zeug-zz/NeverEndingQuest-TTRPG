# Tasks: Accurate-Ingest Seed Writer Completion

## 1. Baseline Review

- [x] 1.1 Review `utils/toolkit_blueprint_seed_writer.py` current helper structure and status constants.
- [x] 1.2 Review downstream seed consumers: `scripts/homebrew_prewarm_portraits.py`, `scripts/homebrew_materialize_monsters.py`, `utils/module_mmg_authority.py`, and `utils/module_monster_authority.py`.
- [x] 1.3 Review `scripts/test_toolkit_blueprint_seed_writer.py` fixture helpers and Numillian-like tests.

## 2. Seed Artifact Emission

- [x] 2.1 Add constants for `toolkit_npc_seed.v1`, `toolkit_monster_seed.v1`, and `toolkit_seed_source_report.v1`.
- [x] 2.2 Add helper to build `npcs_seed.json` from blueprint `npc_roster` with names, aliases, role, faction, location binding, criticality, and source refs.
- [x] 2.3 Add helper to build `monsters_seed.json` conservatively from `encounter_plan`, source monster hints, and structured location monster refs when available.
- [x] 2.4 Add helper to build `seed_source_report.json` with source order, original names, blueprint IDs, source refs, and coverage metadata.
- [x] 2.5 Update dry-run planned file computation to include `npcs_seed.json`, `monsters_seed.json`, and `seed_source_report.json`.
- [x] 2.6 Write the three new artifacts during non-dry-run materialization.

## 3. Failure Semantics

- [x] 3.1 Define required vs optional seed artifact classification inside the seed writer.
- [x] 3.2 Update write tracking so required write failures prevent `seed_status: success`.
- [x] 3.3 Return explicit blockers for missing required artifacts.
- [x] 3.4 Return degraded status and warnings for optional artifact failures where appropriate.
- [x] 3.5 Preserve blocked/non-v2/directory-exists refusal behavior.

## 4. Tests

- [x] 4.1 Extend `scripts/test_toolkit_blueprint_seed_writer.py` to assert `npcs_seed.json` is emitted and contains source NPC names.
- [x] 4.2 Extend tests to assert `monsters_seed.json` is emitted for blueprint encounter/monster hints.
- [x] 4.3 Extend dry-run tests to assert planned files include new seed/report artifacts and no files are written.
- [x] 4.4 Add write-failure tests proving required write failure does not return success.
- [x] 4.5 Add Numillian-like test proving source location order and source refs are represented in `seed_source_report.json`.
- [x] 4.6 Add compatibility test proving existing core files are still emitted.

## 5. Verification

- [x] 5.1 Run `.venv/bin/python -m py_compile utils/toolkit_blueprint_seed_writer.py scripts/test_toolkit_blueprint_seed_writer.py`.
- [x] 5.2 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_seed_writer`.
- [x] 5.3 Run `openspec validate toolkit-accurate-ingest-seed-writer-completion`.
- [x] 5.4 Run targeted ASCII compliance on changed Python files.

## Builder Guidance

Use micro-edits. Touch `utils/toolkit_blueprint_seed_writer.py` and `scripts/test_toolkit_blueprint_seed_writer.py` first. Avoid route, finisher, publishability, and GUI changes in this slice unless tests reveal a narrow compatibility import needs updating.
