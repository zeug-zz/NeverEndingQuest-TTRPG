# Tasks: Accurate-Ingest GUI Builder Unification

## 1. Review And Baseline

- [x] 1.1 Read `plans/accurate-ingest.md` Phase 12 and confirm this change matches the roadmap.
- [x] 1.2 Review current artifact helpers in `utils/toolkit_homebrew_upload_contract.py`.
- [x] 1.3 Review current v1 blueprint behavior in `utils/toolkit_builder_blueprint.py`.
- [x] 1.4 Review deterministic content-block parser behavior in `core/importers/homebrewery_importer.py`.
- [x] 1.5 Review GUI job flow in `web/routes/toolkit_homebrew_routes.py` and packet build flow in `web/extensions/toolkit_homebrew_packet_builder.py`.
- [x] 1.6 Review finisher `MODULE_SUMMARY.md` generation in `web/extensions/toolkit_module_finisher.py` and `utils/homebrewery_adventure_writer.py`.

## 2. Feature Flags

- [x] 2.1 Add `ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD = False` to `model_config.py`.
- [x] 2.2 Add `ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT = False` to `model_config.py`.
- [x] 2.3 Add matching documentation/comments to `config_template.py` if project convention requires user-facing flag docs.
- [x] 2.4 Add source-contract tests proving both flags exist and default to disabled.

## 3. Blueprint v2 Contract

- [x] 3.1 Extend `utils/toolkit_builder_blueprint.py` with `BUILDER_BLUEPRINT_V2_VERSION = "source_faithful_builder_blueprint.v2"`.
- [x] 3.2 Add `generate_builder_blueprint_v2(...)` that consumes existing source graph, identity, topology, normalized packet, deterministic content-block metadata, and fidelity reports.
- [x] 3.3 Preserve existing v1 helpers and behavior for current blueprint narrative handoff.
- [x] 3.4 Populate v2 `module` with title, source path/hash, author/license, estimated level range, source rights, summary, and tone profile.
- [x] 3.5 Populate v2 `source_lock` with canonical names, required omission blocking, invention blocking, replacement plotline blocking, puzzle rewrite blocking, and summary-derived-only flags.
- [x] 3.6 Populate v2 `area_plan` and `location_roster` from deterministic content blocks and/or source graph location atoms, preserving source order and original names.
- [x] 3.7 Populate v2 `npc_roster` from identity/source graph atoms with aliases, role, faction/disposition hints, location bindings, criticality, and source refs.
- [x] 3.8 Populate v2 `plot_graph`, `puzzle_graph`, and `clue_graph` from plot topology and source graph atoms.
- [x] 3.9 Populate v2 `encounter_plan` and `item_roster` from source graph encounter/item atoms and normalized packet hints.
- [x] 3.10 Populate v2 `enrichment_allowlist` with allowed text fields and budgets.
- [x] 3.11 Add `validate_builder_blueprint_v2(...)` returning status, blockers, warnings, and coverage counts.
- [x] 3.12 Persist v2 through the existing `builder_blueprint.json` artifact path with explicit version field.
- [x] 3.13 Add tests in `scripts/test_toolkit_blueprint_v2_contract.py` covering required fields, source locks, Numillian-like map-key locations, blocked missing required sections, and v1 compatibility.

## 4. Deterministic Seed Writer

- [x] 4.1 Create `utils/toolkit_blueprint_seed_writer.py` with standard SPDX header and project docstring.
- [x] 4.2 Add public helper `materialize_module_from_blueprint(blueprint, module_dir, overwrite=False, dry_run=False)`.
- [x] 4.3 Validate blueprint version and refuse blocked/failed/non-v2 blueprints unless explicitly allowed for tests.
- [x] 4.4 Create module directory and deterministic report shape without mutating files when `dry_run=True`.
- [x] 4.5 Emit `module_context.json` and `module_context_BU.json` from module/npc/entity blueprint data.
- [x] 4.6 Emit `module_plot.json` and `module_plot_BU.json` from plot, puzzle, and clue blueprint data.
- [x] 4.7 Emit `areas/*_BU.json` and runtime area JSON from area/location rosters.
- [x] 4.8 Emit `map_*.json` using blueprint connectivity and existing spatial helpers where practical.
- [x] 4.9 Emit NPC/monster seed artifacts required by media prewarm and materialization.
- [x] 4.10 Preserve source name, source order, blueprint IDs, and source refs either in schema-valid fields or workspace-side reports.
- [x] 4.11 Return `seed_status`, created files, skipped files, blockers, warnings, and coverage counts.
- [x] 4.12 Add tests in `scripts/test_toolkit_blueprint_seed_writer.py` proving provider-free materialization, schema-valid core files, source name preservation, dry-run no-write behavior, and refusal for blocked blueprints.

## 5. Bounded Enrichment Patch Pipeline

- [x] 5.1 Create `utils/toolkit_blueprint_enrichment.py` with standard SPDX header and project docstring.
- [x] 5.2 Define patch operation schema: op, blueprint_id, target_file, json_path, field, source_refs, reason, value.
- [x] 5.3 Add `validate_enrichment_patch(...)` that only accepts approved text fields and rejects structure edits.
- [x] 5.4 Add `apply_enrichment_patches(...)` that writes validated patches atomically and returns accepted/rejected operation lists.
- [x] 5.5 Add no-provider mode that returns skipped/degraded reports when enrichment flag is disabled.
- [x] 5.6 Add LLM orchestration only behind `ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT`.
- [x] 5.7 Add prompt file `prompts/toolkit/blueprint_field_enrichment_prompt.txt` with JSON-only patch contract.
- [x] 5.8 Split enrichment into small passes: module overview, area/location prose, NPC prose, plot prose, encounter/treasure prose.
- [x] 5.9 Ensure failed enrichment preserves seeded module content and does not block unless patch validation detects structural mutation attempts.
- [x] 5.10 Add tests in `scripts/test_toolkit_blueprint_enrichment_patches.py` for accepted text patches, rejected rename/ID/connectivity/puzzle-rule patches, disabled flag behavior, and atomic write behavior.

## 6. Packet Builder Integration

- [x] 6.1 Update `web/extensions/toolkit_homebrew_packet_builder.py` to classify v2 source-blueprint builds separately from v1 narrative-only handoff.
- [x] 6.2 When `ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD` is false, preserve existing behavior exactly.
- [x] 6.3 When flag is true and v2 blueprint is ready, call the seed writer instead of `ModuleBuilder.build_module(...)`.
- [x] 6.4 After seeding, call bounded enrichment helper and record enrichment status in `build_result.json`.
- [x] 6.5 Run existing build-fidelity gate after seed/enrichment and before readiness/finisher.
- [x] 6.6 Fail closed when accurate-ingest artifacts require blueprint build but v2 blueprint is missing, invalid, blocked, or stale.
- [x] 6.7 Preserve legacy packet workspaces and Describe-your-Adventure builds.
- [x] 6.8 Add source-contract and behavior tests in `scripts/test_toolkit_homebrew_gui_unified_flow.py` with mocked seed/enrichment helpers.

## 7. GUI Route State Surfacing

- [x] 7.1 Extend `web/routes/toolkit_homebrew_routes.py` job state payloads with accurate-ingest unified states: extracting_source_truth, building_blueprint, seeding_module, enriching_module, build_fidelity.
- [x] 7.2 Surface source structure counts, blueprint status, seed status, enrichment status, and source-fidelity status in job review/status responses.
- [x] 7.3 Ensure fidelity review approval is still required before seed/enrichment begins.
- [x] 7.4 Ensure rebuild/overwrite confirmation still runs before writing module files.
- [x] 7.5 Ensure active job locking still prevents concurrent builds.
- [x] 7.6 Add route tests proving one user-visible GUI operation can progress through review, seed, enrichment, readiness, finisher, and final status with mocked helpers.

## 8. Shared Finisher And MODULE_SUMMARY.md

- [x] 8.1 Confirm every successful v2 accurate-ingest GUI build calls `_run_homebrew_readiness_gate(...)` and `_run_homebrew_finisher(...)`.
- [x] 8.2 Ensure `toolkit_build_report.json` includes `source_fidelity_status`, seed status, enrichment status, and `module_summary` path when available.
- [x] 8.3 Ensure `MODULE_SUMMARY.md` generation remains in `web/extensions/toolkit_module_finisher.py` after materialization/classification and before final report write.
- [x] 8.4 Ensure `MODULE_SUMMARY.md` generation failure degrades report status but does not mutate module JSON.
- [x] 8.5 Ensure cached summary download path remains disk-first and does not regenerate when a valid file exists.
- [x] 8.6 Add tests in `scripts/test_toolkit_module_summary_finisher_contract.py` proving summary is final-derived output and not a source-fidelity repair path.

## 9. Final Source-Fidelity And Benchmark Integration

- [x] 9.1 Ensure `source_fidelity_report.json` is generated after v2 seed/enrichment builds.
- [x] 9.2 Ensure `scripts/audit_module_publishability.py` reads the final source-fidelity status unchanged.
- [x] 9.3 Ensure blocked source fidelity prevents publishability even if readiness passes.
- [x] 9.4 Add/extend `scripts/test_accurate_ingest_numillian_end_to_end.py` with a fixture-driven GUI-equivalent path.
- [x] 9.5 Verify Numillian expectations: 13 source locations, NPC threshold, Trial-at-the-Door puzzles, Gatepact lore, Kobe protection, and no generic conspiracy replacement.
- [x] 9.6 Verify `MODULE_SUMMARY.md` reflects final audited module content.

## 10. Verification

- [x] 10.1 Run `.venv/bin/python -m py_compile` on all modified Python files.
- [x] 10.2 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_v2_contract`.
- [x] 10.3 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_seed_writer`.
- [x] 10.4 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_enrichment_patches`.
- [x] 10.5 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow`.
- [x] 10.6 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_module_summary_finisher_contract`.
- [x] 10.7 Run `.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_end_to_end`.
- [x] 10.8 Run `.venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json`.
- [x] 10.9 Run `.venv/bin/python -m unittest -q scripts.test_audit_module_publishability`.
- [x] 10.10 Run `openspec validate toolkit-accurate-ingest-gui-builder-unification`.
- [x] 10.11 Run targeted ASCII compliance on changed Python/prompt files.

## Implementation Notes

- Keep first implementation feature-flagged and default-off for blueprint-native GUI build and enrichment.
- Do not remove the current v1 blueprint narrative handoff until v2 path passes Numillian end-to-end.
- Do not let `MODULE_SUMMARY.md` affect source-fidelity scores.
- Use `.venv/bin/python` for runtime and dependency-sensitive tests.
- Prefer small helper modules over broad rewrites of `ModuleBuilder` internals.
