# Executor Prompts: Accurate-Ingest GUI Builder Unification

Use these prompts sequentially. They are written for a smaller builder model such as Deepseek V4 Flash: narrow scope, explicit files, explicit checks. Do not skip verification between prompts.

## Prompt 1: Blueprint v2 Contract Only

```text
Implement only the blueprint v2 contract for OpenSpec change `toolkit-accurate-ingest-gui-builder-unification`.

Goal:
Extend accurate-ingest blueprint generation so `builder_blueprint.json` can carry a `source_faithful_builder_blueprint.v2` contract. Preserve existing v1 behavior.

Allowed files:
- `utils/toolkit_builder_blueprint.py`
- `utils/toolkit_homebrew_upload_contract.py` only if a tiny artifact helper is needed
- `model_config.py` and `config_template.py` only for feature flags if not already added
- `scripts/test_toolkit_blueprint_v2_contract.py`

MUST:
1. Add constant `BUILDER_BLUEPRINT_V2_VERSION = "source_faithful_builder_blueprint.v2"`.
2. Add helper `generate_builder_blueprint_v2(...)` or equivalent. It must consume existing artifacts: source graph, identity report, plot topology report, normalized packet, and fidelity report.
3. Output top-level fields: `blueprint_version`, `blueprint_status`, `source_hash`, `module`, `source_lock`, `area_plan`, `location_roster`, `npc_roster`, `plot_graph`, `puzzle_graph`, `clue_graph`, `encounter_plan`, `item_roster`, `enrichment_allowlist`, `artifact_refs`, `coverage`, `warnings`, `blockers`.
4. Preserve source names and source order for locations where source graph/content-block metadata provides it.
5. Add validation helper returning status, blockers, warnings, and coverage.
6. Do not remove or break v1 `serialize_builder_blueprint_to_narrative(...)` behavior.
7. Tests must cover required fields, locks, blocked missing required location, Numillian-like 13 map-key roster, and v1 compatibility.

MUST NOT:
- Do not edit GUI routes.
- Do not call LLM providers.
- Do not write module files.
- Do not change `ModuleBuilder` internals.

Verification:
- `.venv/bin/python -m py_compile utils/toolkit_builder_blueprint.py scripts/test_toolkit_blueprint_v2_contract.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_v2_contract`
- `openspec validate toolkit-accurate-ingest-gui-builder-unification`
```

## Prompt 2: Deterministic Seed Writer

```text
Implement only the deterministic seed writer for blueprint v2.

Goal:
Create a provider-free helper that materializes a schema-valid skeletal NEQ module from `builder_blueprint.v2` before any LLM enrichment.

Allowed files:
- `utils/toolkit_blueprint_seed_writer.py` (new)
- `scripts/test_toolkit_blueprint_seed_writer.py` (new)
- Existing utility imports only as needed (`utils.file_operations`, spatial helpers, encoding helpers)

MUST:
1. Add standard SPDX header and project docstring.
2. Add public helper `materialize_module_from_blueprint(blueprint, module_dir, overwrite=False, dry_run=False)`.
3. Refuse blocked/failed/non-v2 blueprints by default.
4. In dry-run mode, return planned files and coverage without writing.
5. Emit `module_context.json`, `module_context_BU.json`, `module_plot.json`, `module_plot_BU.json`, `areas/*_BU.json`, runtime area JSON, and `map_*.json` from blueprint rosters.
6. Preserve source location names, NPC names, source order, plot IDs, puzzle facts, and connectivity hints.
7. Emit seed artifacts for NPC/monster media/materialization if practical; otherwise include a warning and clear TODO marker in report.
8. Return report fields: `seed_status`, `module_dir`, `created_files`, `skipped_files`, `coverage`, `warnings`, `blockers`.

MUST NOT:
- Do not call LLM providers.
- Do not run the GUI route.
- Do not generate `MODULE_SUMMARY.md` here.
- Do not overwrite existing module directories unless `overwrite=True`.

Verification:
- `.venv/bin/python -m py_compile utils/toolkit_blueprint_seed_writer.py scripts/test_toolkit_blueprint_seed_writer.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_seed_writer`
- `openspec validate toolkit-accurate-ingest-gui-builder-unification`
```

## Prompt 3: Bounded Enrichment Patch Pipeline

```text
Implement only blueprint bounded enrichment patch validation and disabled-mode behavior first. Add provider orchestration only if validation tests pass.

Goal:
Allow LLMs to improve seeded module prose through validated patch operations while forbidding structural changes.

Allowed files:
- `utils/toolkit_blueprint_enrichment.py` (new)
- `prompts/toolkit/blueprint_field_enrichment_prompt.txt` (new)
- `scripts/test_toolkit_blueprint_enrichment_patches.py` (new)
- `model_config.py` if feature flag is missing

MUST:
1. Define patch operation schema fields: `op`, `blueprint_id`, `target_file`, `json_path`, `field`, `source_refs`, `reason`, `value`.
2. Accept only approved text fields from the spec: NPC description/role/faction, plot mainObjective/description/plotImpact, areaDescription, location description/dmInstructions/adventureSummary/existing plotHooks strings.
3. Reject attempts to change names, IDs, connectivity, source refs, puzzle rules, plot dependencies, or file paths outside the module.
4. Add `validate_enrichment_patch(...)` and `apply_enrichment_patches(...)`.
5. When `ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT` is false, return skipped status and make no provider calls.
6. Provider failures must degrade without corrupting seeded files.
7. Use atomic writes or existing safe write helpers.

MUST NOT:
- Do not run enrichment automatically from GUI yet.
- Do not allow destructive JSON operations.
- Do not modify module structure.

Verification:
- `.venv/bin/python -m py_compile utils/toolkit_blueprint_enrichment.py scripts/test_toolkit_blueprint_enrichment_patches.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_enrichment_patches`
- `openspec validate toolkit-accurate-ingest-gui-builder-unification`
```

## Prompt 4: Packet Builder Integration Behind Flag

```text
Integrate the v2 seed/enrichment path into packet builder behind `ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD`.

Goal:
When a workspace has a ready v2 blueprint and the feature flag is enabled, build via deterministic seed writer plus optional enrichment instead of `ModuleBuilder.build_module(...)`. Preserve existing behavior when disabled.

Allowed files:
- `web/extensions/toolkit_homebrew_packet_builder.py`
- `scripts/test_toolkit_homebrew_gui_unified_flow.py`
- Possibly `utils/toolkit_homebrew_upload_contract.py` for tiny report artifact helpers only

MUST:
1. Classify handoff modes: legacy_allowed, source_blueprint_v1_narrative, source_blueprint_v2_native, blueprint_required_not_ready.
2. If flag is false, preserve current behavior exactly.
3. If flag is true and v2 blueprint is ready, call `materialize_module_from_blueprint(...)`.
4. Call enrichment helper after seeding and record skipped/degraded/success status in build result.
5. Run existing build-fidelity gate after seed/enrichment.
6. Persist `build_result.json` with seed/enrichment/build_fidelity details.
7. Fail closed before writing if accurate-ingest artifacts imply blueprint required but v2 is invalid/blocked/stale.

MUST NOT:
- Do not edit route state machine yet except tests using packet builder directly.
- Do not break v1 narrative handoff or legacy packet builds.
- Do not skip build-fidelity gates.

Verification:
- `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py scripts/test_toolkit_homebrew_gui_unified_flow.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow`
- Existing packet builder tests if present: `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_packet_builder`
- `openspec validate toolkit-accurate-ingest-gui-builder-unification`
```

## Prompt 5: GUI Route States And Review Surface

```text
Add GUI job states and status payloads for the unified accurate-ingest flow.

Goal:
Expose source extraction, blueprint, seed, enrichment, build-fidelity, readiness, finisher, and final artifacts as one coherent Module Builder GUI workflow.

Allowed files:
- `web/routes/toolkit_homebrew_routes.py`
- `web/templates/module_toolkit.html` only if minimal labels/status rendering is needed
- `scripts/test_toolkit_homebrew_gui_unified_flow.py`

MUST:
1. Add state names: `extracting_source_truth`, `building_blueprint`, `seeding_module`, `enriching_module`, `build_fidelity`.
2. Keep existing review approval gate before seed/enrichment begins.
3. Surface compact counts/status: source locations, NPCs, puzzles, blueprint status, seed status, enrichment status, source fidelity status.
4. Preserve overwrite confirmation/rebuild handling.
5. Preserve active job locking.
6. Add tests with mocked helpers proving job can move through approved review -> seed/enrich -> readiness -> finisher -> completed/not_publishable.

MUST NOT:
- Do not weaken fidelity review approval.
- Do not make summary generation a source-fidelity repair.
- Do not remove legacy route behavior.

Verification:
- `.venv/bin/python -m py_compile web/routes/toolkit_homebrew_routes.py scripts/test_toolkit_homebrew_gui_unified_flow.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow`
- `openspec validate toolkit-accurate-ingest-gui-builder-unification`
```

## Prompt 6: Finisher And MODULE_SUMMARY.md Contract

```text
Verify and harden the final finisher path for blueprint-native accurate-ingest builds.

Goal:
Ensure every successful unified GUI build enters existing toolkit finishing and generates cached `MODULE_SUMMARY.md` as final presentation output.

Allowed files:
- `web/extensions/toolkit_module_finisher.py`
- `utils/homebrewery_adventure_writer.py` only if summary rendering needs small contract fixes
- `web/web_interface.py` only if cached download endpoint needs contract assertion/fix
- `scripts/test_toolkit_module_summary_finisher_contract.py`

MUST:
1. Confirm finisher report includes module_summary stage with status/path/bytes.
2. Confirm summary generation failure degrades but does not mutate JSON files.
3. Confirm cached summary download remains disk-first.
4. Confirm source-fidelity blockers are not satisfied by summary prose alone.
5. Add tests for final-derived output behavior.

MUST NOT:
- Do not move summary generation before fidelity/readiness checks.
- Do not let summary generation repair module data.

Verification:
- `.venv/bin/python -m py_compile web/extensions/toolkit_module_finisher.py utils/homebrewery_adventure_writer.py scripts/test_toolkit_module_summary_finisher_contract.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_module_summary_finisher_contract`
- `openspec validate toolkit-accurate-ingest-gui-builder-unification`
```

## Prompt 7: Numillian End-To-End Benchmark

```text
Add final end-to-end regression coverage using Numillian or a compact Numillian-like fixture.

Goal:
Prove the unified GUI-equivalent path preserves source truth through blueprint, seed, enrichment, finisher, summary, and publication gate reports.

Allowed files:
- `scripts/test_accurate_ingest_numillian_end_to_end.py`
- Existing benchmark fixture files only if a tiny fixture correction is required
- No broad production code unless tests reveal a narrow bug

MUST:
1. Use `.venv/bin/python` test environment.
2. Avoid provider calls; mock enrichment if needed.
3. Assert 13 source locations survive by original name or approved mapping.
4. Assert required puzzle/lore expectations survive or source-fidelity blocks publication.
5. Assert final report has source_fidelity_status.
6. Assert `MODULE_SUMMARY.md` exists for successful finisher path and reflects final module data.

MUST NOT:
- Do not commit generated runtime artifacts from test temp dirs.
- Do not call real LLM providers.
- Do not mutate live Numillian module unless explicitly approved.

Verification:
- `.venv/bin/python -m py_compile scripts/test_accurate_ingest_numillian_end_to_end.py`
- `.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_end_to_end`
- `.venv/bin/python scripts/test_accurate_ingest_numillian_benchmark.py`
- `.venv/bin/python scripts/test_audit_module_publishability.py`
- `openspec validate toolkit-accurate-ingest-gui-builder-unification`
```
