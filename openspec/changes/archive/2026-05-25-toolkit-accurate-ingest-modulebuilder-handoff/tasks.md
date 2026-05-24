# Tasks

## 0. Scaffold and Planning

- [x] 0.1 Update `plans/accurate-ingest-fix.md` current disposition for the archived Numillian preservation change.
- [x] 0.2 Create OpenSpec proposal, design, tasks, and delta specs for ModuleBuilder handoff.
- [x] 0.3 Add Step 1.1 full builder prompt to `builder_prompts.md`.
- [x] 0.4 Validate OpenSpec scaffold.

## 1. Handoff Regression Locks

- [x] 1.1 Add deterministic tests proving default accurate-ingest packet builds route to `_execute_module_builder(...)`, not `_execute_seed_writer_build(...)`, when no explicit seed writer mode is supplied.
> Existing `TestPacketBuilderV2Integration.test_default_no_seed_mode_uses_module_builder` covers all MUST requirements: patches both executors, asserts ModuleBuilder called once, seed writer not called, `build_mode` is `source_enhanced_modulebuilder`, no `seed_writer_mode` in result. 79 GUI tests pass.
- [x] 1.2 Add deterministic tests proving explicit seed writer modes (`fallback`, `preview`, `support`) still route to `_execute_seed_writer_build(...)` and report `seed_writer_mode`.
> Added `test_seed_writer_mode_explicit_fallback` to `TestPacketBuilderV2Integration` matching the `preview`/`support` pattern. All three modes now have provider-free tests asserting `_execute_seed_writer_build` called once, correct `build_mode` (`blueprint_seed_fallback`/`preview`/`support`), and matching `seed_writer_mode`. 80 GUI tests pass.
- [x] 1.3 Add deterministic tests proving builder handoff artifacts include required Numillian source NPC, location, puzzle/challenge, and tone tokens before ModuleBuilder runs.
> Added `test_handoff_includes_source_contract_npc_location_puzzle_tone` to `TestPacketBuilderV2Integration`. Captures `builder_input` passed to patched `_execute_module_builder`. Asserts `handoff_mode: source_blueprint`, all four `source_lock` fields (canonical_names_locked, invented_major_entities_forbidden, replacement_plotlines_forbidden, puzzle_rule_rewrite_forbidden), source artifact paths, and Numillian source tokens (3 NPCs, 3 locations, 3 puzzle IDs, tone marker) via the referenced workspace blueprint. 81 GUI tests pass.
- [x] 1.4 Add deterministic tests proving malformed or non-ready blueprint artifacts still fail closed before ModuleBuilder execution.
> Added 3 tests: `test_blocked_blueprint_does_not_call_module_builder` (blocked blueprint asserts executor not called), `test_blocked_report_does_not_call_module_builder` (ready blueprint + blocked report asserts executor not called), `test_empty_blueprint_fails_closed` (empty `{}` blueprint asserts executor not called). All three patch `_execute_module_builder` and assert `mock_executor.assert_not_called()`. 84 GUI tests pass.

## 2. Handoff Artifact Enrichment

- [x] 2.1 Inspect current `builder_input.json` and `builder_narrative` content produced for v2 accurate-ingest workspaces.
> Current `builder_input` shape: `status`, `stage`, `created_at`, `job_id`, `build_mode`, `packet_identity`, `review_snapshot`, `derived_builder_parameters`, `builder_narrative_source`, `builder_narrative`. When v2 ready blueprint + report exist: `handoff_mode: "source_blueprint"` + `blueprint` block with `source_lock` and `source_artifacts`. NPC/location/puzzle/tone tokens were only in the referenced workspace blueprint, not in `builder_input` directly.
- [x] 2.2 Add the minimal source-contract serialization needed for required NPCs, locations, puzzles, tone, and forbidden-invention guidance.
> Added extraction from `blueprint_artifact` into `builder_input` at lines ~569-602 in `toolkit_homebrew_packet_builder.py`. Four new fields: `source_npc_names` (from `npc_roster`, reads `name` or `display_name`), `source_location_names` (from `location_roster`, reads `name` or `display_name`), `source_puzzle_ids` (from `puzzle_graph`, reads `puzzle_id` or `chain_id` or `title`), `source_tone` (from `tone_requirements`, normalizes string to single-item list). All are conditional — only added when blueprint has the relevant data. Corrective patch (2026-05-25) fixed key mismatch with production synthetic blueprint shape.
- [x] 2.3 Persist the handoff artifact with clear `build_mode`, source hash, and handoff metadata.
> `persist_builder_input_artifact` serializes the dict as JSON; new fields included automatically. No additional changes needed.
- [x] 2.4 Verify source-contract tests pass without live provider calls.
> Strengthened `test_handoff_includes_source_contract_npc_location_puzzle_tone`: fixture uses production-like shape (`display_name`, `chain_id`/`title`, tone as string). 12 assertions verify fields directly in `builder_input`. Added persistence assertion: reads `builder_input.json` from workspace and verifies same fields. Corrective patch (2026-05-25) aligned fixture with real synthetic blueprint schema. 84 GUI tests pass.

## 3. Routing and Reporting Verification

- [x] 3.1 Verify default v2 accurate-ingest path reports `source_enhanced_modulebuilder`.
> `test_default_no_seed_mode_uses_module_builder` already asserts `build_mode == "source_enhanced_modulebuilder"`.
- [x] 3.2 Verify seed writer explicit modes report `blueprint_seed_fallback`, `blueprint_seed_preview`, or `blueprint_seed_support`.
> `test_seed_writer_mode_explicit_fallback`, `test_seed_writer_mode_explicit_preview`, and `test_seed_writer_mode_explicit_support` assert correct build_modes.
- [x] 3.3 Verify existing Describe-your-Adventure or non-source packet path remains functional.
> Added `test_legacy_non_source_path_routes_to_module_builder`: patches `ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF=False`, asserts `_execute_module_builder` called, `build_mode == "packet_workspace_v1"`.
- [x] 3.4 Verify no production Numillian module artifacts are modified.
> 28 Numillian files show pre-existing diffs from `56bab1d` (May 23 source-fidelity bridge fix). Our change touched only `toolkit_homebrew_packet_builder.py` (+29) and `test_toolkit_homebrew_gui_unified_flow.py` (+167). 85 GUI tests pass.
> Corrective patch (2026-05-25): gated source-contract serialization behind `blueprint_metadata` so legacy-disabled paths stay clean even with stale blueprint artifacts. Strengthened `test_legacy_non_source_path_routes_to_module_builder` to assert source fields are absent from `builder_input` under `ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF=False`.

## 4. Final Verification

- [x] 4.1 Run compile checks for modified files.
> `py_compile` passes for all 4 targets.
- [x] 4.2 Run targeted GUI packet builder tests.
> 85/85 pass.
- [x] 4.3 Run targeted blueprint v2 contract tests.
> 33/33 pass.
- [x] 4.4 Validate the OpenSpec change.
> `openspec validate` passes.

## Suggested Verification Commands

```bash
.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py scripts/test_toolkit_homebrew_gui_unified_flow.py scripts/test_toolkit_blueprint_v2_contract.py scripts/test_accurate_ingest_numillian_end_to_end.py
.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow
.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_v2_contract
.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_end_to_end
openspec validate toolkit-accurate-ingest-modulebuilder-handoff
```
