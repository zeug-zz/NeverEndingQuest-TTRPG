# Tasks

## 0. Scaffold And Validation

- [x] 0.1 Create proposal, design, tasks, delta specs, and builder prompt artifact.
- [x] 0.2 Validate the OpenSpec scaffold.

> `openspec validate toolkit-accurate-ingest-monster-encounter-materialization` -> valid.

## 1. Source Monster Materialization Contract

- [x] 1.1 Add provider-free tests for a materialization helper input/output contract using temp module fixtures and source monster refs.
    - Created `utils/accurate_ingest_monster_materialization.py` with `materialize_source_monsters()` stub.
    - Created `scripts/test_accurate_ingest_monster_materialization.py` with 19 tests across 7 test classes.
    - Report shape, deterministic, reusable ref, odd/unresolved ref, NPC-like rejection, no-source compatibility, encounter seed binding contracts all covered.
- [x] 1.2 Implement or identify a narrow helper that accepts source monster refs and returns deterministic materialization diagnostics.
    - Implemented `materialize_source_monsters()` in `utils/accurate_ingest_monster_materialization.py`.
    - Reuse-first resolution: checks `module_dir/monsters/<normalized>.json` for each ref.
    - Original refs preserved in `unresolved_refs`; resolved refs tracked in `monsters_reused` and `artifact_paths`.
    - Status: `skipped` (no refs/seeds), `pass` (all resolved), `degraded` (any unresolved).
    - All 19 Step 1.1 tests pass including the 2 previously skipped reusable-ref tests.
- [x] 1.3 Ensure unambiguous reusable refs can materialize schema-valid module-local `monsters/*.json` files.
    - Added `_MONSTER_REQUIRED_FIELDS = {"size", "alignment", "armorClass"}` and `_is_schema_sufficient()` to the helper.
    - Reuse now requires valid JSON + all required fields present.
    - Invalid JSON, missing `armorClass`, missing `size`, and missing `alignment` all remain unresolved.
    - 5 new tests in `TestSchemaInsufficientMonsterFiles`: valid-is-reused, invalid-json, missing-armorClass, missing-size, missing-alignment.
    - Helper normalization is local/provider-free; no runtime character update import.
    - All 25 tests pass.
- [x] 1.4 Ensure unresolved refs are reported explicitly and are not silently dropped.
    - Added `resolution_log: List[Dict]` to report with per-ref entries for every source ref.
    - Each entry carries `ref`, `status` (reused/unresolved), `reason` (reused, file_not_found, invalid_json, missing_required_fields), and `artifact_path`.
    - `unresolved_refs` and `artifact_paths` derived from `resolution_log`.
    - 8 new resolution-log tests total: `test_resolution_log_is_list` plus 7 tests in `TestResolutionLog` covering one-entry-per-ref, reused-entry, file-not-found-entry, invalid-json-entry, missing-fields-entry, empty-refs-empty-log, and deterministic-log.
    - All 33 tests pass.

## 2. Encounter Seed Monster Binding

- [x] 2.1 Add provider-free tests proving encounter seeds retain monster refs and source evidence through binding.
    - Added `bind_encounter_monsters()` stub in test file with contract-shaped report.
    - Added `TestEncounterBindingContract` with 10 tests covering report shape, resolvable refs, unresolvable refs, mixed diagnostics, no-ref pass-through, empty input, and determinism.
    - 4 binding-behavior tests correctly skip until Step 2.2 implementation.
    - All 33 existing materialization tests remain passing.
    - All 43 tests pass (4 skipped).
- [x] 2.2 Bind encounter seed or encounter-plan entries to canonical materialized monster IDs when unambiguous.
    - Implemented `bind_encounter_monsters()` in `utils/accurate_ingest_monster_materialization.py` with token-substring matching.
    - Moved from test-local stub to production utility; tests now import from module.
    - Binding logic: reused ref match -> bound; unresolved ref match -> unresolved; no match -> unbound.
    - Report status: `skipped` (no input), `pass` (no unresolved seeds), `degraded` (any unresolved seeds).
    - All 43 tests pass, 0 skipped. 4 formerly skipped binding-behavior tests now execute and pass.
- [x] 2.3 Preserve unresolved encounter monster refs as diagnostics without deleting encounter seeds.
    - Added 4 tests proving: unresolved ref stays attached to its seed, all seeds represented in bindings, bound seed gets correct matched ref, unresolved ref does not leak into `monster_ref`/`artifact_path`.
    - All 47 tests pass, 0 skipped.

## 3. Reporting And Compatibility

- [x] 3.1 Add deterministic report fields for planned, reused, generated, bound, skipped, and unresolved monster/encounter refs.
    - Added `monsters_skipped`, `encounters_unresolved`, `encounters_unbound`, `encounter_bindings` to `materialize_source_monsters()` report.
    - Added `seeds_unbound` to `bind_encounter_monsters()` report.
    - `materialize_source_monsters()` now composes `bind_encounter_monsters()` for accurate binding counts.
    - Status derivation includes both monster-ref unresolved stats and encounter binding status.
    - All 50 tests pass, 0 skipped.
- [x] 3.2 Verify no-source and legacy concept-builder paths do not emit false monster blockers.
    - Legacy/blueprint tests pass (126/126 PASS): `scripts.test_toolkit_homebrew_gui_unified_flow`, `scripts.test_toolkit_blueprint_v2_contract`.
    - No-source test confirms `materialize_source_monsters([], [])` returns `skipped` with no false blockers.
- [x] 3.3 Verify source-fidelity, readiness, validation, and publishability gates are not weakened or bypassed.
    - Numillian benchmark/end-to-end tests pass (153/153 PASS, 3 pre-existing skipped).
    - Compile check passes for `toolkit_homebrew_packet_builder`, `module_monster_authority`, `toolkit_build_fidelity`, `accurate_ingest_monster_materialization`.

## 4. Final Verification

- [x] 4.1 Run compile checks for modified Python files.
    - `py_compile` on `toolkit_homebrew_packet_builder`, `module_monster_authority`, `toolkit_build_fidelity`, `accurate_ingest_monster_materialization` -> PASS.
- [x] 4.2 Run targeted materialization and accurate-ingest GUI/blueprint tests.
    - `scripts.test_accurate_ingest_monster_materialization` -> 50/50 PASS.
    - `scripts.test_toolkit_homebrew_gui_unified_flow` + `scripts.test_toolkit_blueprint_v2_contract` -> 126/126 PASS.
- [x] 4.3 Run Numillian benchmark/end-to-end regression tests without production rebuild mutation.
    - `scripts.test_accurate_ingest_numillian_benchmark` + `scripts.test_accurate_ingest_numillian_end_to_end` -> 153/153 PASS (3 pre-existing skipped).
- [x] 4.4 Validate this OpenSpec change.
    - `openspec validate toolkit-accurate-ingest-monster-encounter-materialization` -> valid.

## Suggested Verification Commands

```bash
.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py utils/module_monster_authority.py utils/toolkit_build_fidelity.py utils/accurate_ingest_monster_materialization.py
.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow scripts.test_toolkit_blueprint_v2_contract
.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_benchmark scripts.test_accurate_ingest_numillian_end_to_end
.venv/bin/python -m unittest -q scripts.test_accurate_ingest_monster_materialization
openspec validate toolkit-accurate-ingest-monster-encounter-materialization
```
