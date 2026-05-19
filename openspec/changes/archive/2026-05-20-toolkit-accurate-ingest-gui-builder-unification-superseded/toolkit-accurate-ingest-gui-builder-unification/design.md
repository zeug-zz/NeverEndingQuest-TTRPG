## Overview

This change turns accurate-ingest from a collection of source-fidelity artifacts into a coherent GUI Module Builder pipeline. The design separates structure ownership from prose enrichment:

- Python owns source extraction, blueprint validation, deterministic module seeding, and fidelity gates.
- LLMs enrich only approved text fields using patch operations tied to blueprint IDs and source refs.
- The toolkit finisher owns readiness, semantic publishability, media/materialization, report freshness, and `MODULE_SUMMARY.md` generation.

The first implementation should avoid deep rewrites to `ModuleBuilder` internals. Add a blueprint-native path beside the legacy concept builder, then route accurate-ingest GUI jobs to that path behind feature flags.

## Existing Components To Reuse

| Component | Current Role | Phase 12 Use |
|---|---|---|
| `utils/toolkit_source_manifest.py` | Mechanical source manifest/graph extraction | Feed blueprint v2 and benchmark/fidelity checks |
| `utils/toolkit_source_extraction.py` | Section-bounded LLM fact extraction | Fill source-backed atoms where deterministic graph is insufficient |
| `utils/toolkit_source_graph_synthesis.py` | Identity/topology/packet synthesis | Input to blueprint v2 |
| `utils/toolkit_normalization_fidelity.py` | Packet/source fidelity audit and repair | Pre-blueprint gate |
| `utils/toolkit_builder_blueprint.py` | Current blueprint v1 and source-locked narrative | Upgrade or extend to blueprint v2 |
| `core/importers/homebrewery_importer.py` | Deterministic content-block/map-key parser | Produce blueprint inputs, not just direct skeletal module output |
| `web/extensions/toolkit_homebrew_packet_builder.py` | Current packet build and build-fidelity integration | Route accurate-ingest jobs to seed/enrich path when enabled |
| `utils/toolkit_build_fidelity.py` | Build-time source preservation audit | Run after seed/enrichment before finisher completes |
| `web/extensions/toolkit_module_finisher.py` | Readiness/publishability/media/summary generation | Mandatory final path for successful GUI builds |
| `utils/homebrewery_adventure_writer.py` | `MODULE_SUMMARY.md` generation | Final presentation artifact only |

## Decision 1: Blueprint v2 Is The Build Contract

`builder_blueprint.v2` SHALL be the authoritative build contract for accurate-ingest GUI builds. It SHALL be generated from source graph, content blocks, identity resolution, plot topology, normalized packet, and fidelity reports.

Required top-level fields:

```json
{
  "blueprint_version": "source_faithful_builder_blueprint.v2",
  "blueprint_status": "ready|degraded|blocked|failed",
  "source_hash": "...",
  "module": {},
  "source_lock": {},
  "area_plan": [],
  "location_roster": [],
  "npc_roster": [],
  "plot_graph": {},
  "puzzle_graph": [],
  "clue_graph": [],
  "encounter_plan": [],
  "item_roster": [],
  "enrichment_allowlist": {},
  "artifact_refs": {},
  "coverage": {},
  "warnings": [],
  "blockers": []
}
```

Required source locks:

- `canonical_names_locked: true`
- `required_atom_omission_blocks_build: true`
- `invented_major_entities_forbidden: true`
- `replacement_plotlines_forbidden: true`
- `puzzle_rule_rewrite_forbidden: true`
- `module_summary_is_derived_only: true`

The existing `builder_blueprint.json` file path can continue to be used. The file must declare its version so v1 legacy handoff and v2 native build can be distinguished.

## Decision 2: Deterministic Seed Writer Before Enrichment

Add `utils/toolkit_blueprint_seed_writer.py` with a public helper similar to:

```python
def materialize_module_from_blueprint(
    blueprint: Dict[str, Any],
    module_dir: Path,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    ...
```

Responsibilities:

1. Validate blueprint version/status and refuse `blocked`/`failed` blueprints.
2. Create deterministic module files from source rosters:
   - `module_context.json` and `module_context_BU.json`
   - `module_plot.json` and `module_plot_BU.json`
   - `areas/*_BU.json` and runtime area JSON when required by current toolkit conventions
   - `map_*.json`
   - seed artifacts for NPCs, monsters, and media prewarm
3. Preserve source names and source order.
4. Use existing spatial helpers where practical for coordinates/connectivity.
5. Return a report with created files, coverage counts, warnings, blockers, and `seed_status`.

The seed writer MUST NOT call LLM providers.

## Decision 3: Bounded Enrichment Uses Patch Operations

Add `utils/toolkit_blueprint_enrichment.py` with patch-only orchestration. It should call LLM providers only when `ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT` is true.

Patch operation shape:

```json
{
  "op": "set_text_field|append_text_field|replace_text_field",
  "blueprint_id": "location:NUM03",
  "target_file": "areas/NUM001_BU.json",
  "json_path": "locations[2].dmInstructions",
  "field": "dmInstructions",
  "source_refs": [],
  "reason": "source_preserving_description_enrichment",
  "value": "..."
}
```

Allowed target fields for first implementation:

- `module_context.json` NPC `description`, `role`, `faction`.
- `module_plot_BU.json` `mainObjective`.
- `module_plot_BU.json` plot point `description` and `plotImpact`.
- Area `*_BU.json` `areaDescription`.
- Area location `description`, `dmInstructions`, `adventureSummary`, and existing `plotHooks` strings.

Forbidden changes:

- Rename source locations or NPCs.
- Change location IDs, map keys, connectivity, puzzle rules, plot dependencies, source criticality, or source refs.
- Add major villains, factions, replacement endings, or replacement plotlines.

Patch validation MUST happen before writes. Rejected patches must be recorded in an enrichment report and must not mutate files.

## Decision 4: GUI Job Flow Has Explicit Accurate-Ingest States

The GUI route should route accurate-ingest workspaces through a unified state machine. The practical first implementation can keep the existing `web/routes/toolkit_homebrew_routes.py` job registry and add states rather than replacing it.

Required state order:

1. `preflight`
2. `extracting_source_truth`
3. `building_blueprint`
4. `awaiting_review`
5. `seeding_module`
6. `enriching_module`
7. `build_fidelity`
8. `readiness`
9. `finishing`
10. `publishability_audit`
11. `completed|not_publishable|failed|quarantined`

The GUI should present a single user workflow even if the implementation selects deterministic parsing, multi-pass extraction, or both internally.

## Decision 5: Existing Finisher Remains Mandatory

After seed/enrichment and build-fidelity pass, accurate-ingest GUI builds SHALL enter the existing toolkit finisher. This preserves:

- continuity normalization
- semantic authority
- registry checks
- monster materialization
- LLM classification/remediation metadata
- publishability report freshness
- `MODULE_SUMMARY.md` generation

`MODULE_SUMMARY.md` remains a derived presentation artifact. It must not repair source fidelity, mutate module JSON, or affect benchmark scores except as an output availability signal.

## Decision 6: Feature Flags And Rollout

Add or confirm these flags in `model_config.py`:

```python
ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD = False
ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT = False
```

Rollout:

1. Implement blueprint v2 generation and tests with no GUI behavior change.
2. Implement seed writer behind `ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD`.
3. Enable GUI routing for tests using mocks/fixtures.
4. Implement enrichment behind `ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT`.
5. Run Numillian end-to-end and keep flags off by default until stable.

## Implementation Notes For Builder

Build in small passes. Do not try to rewrite the whole toolkit route in one edit.

Recommended file order:

1. `utils/toolkit_builder_blueprint.py` - add v2 builder and serializer helpers, preserving v1 behavior.
2. `utils/toolkit_blueprint_seed_writer.py` - new deterministic materializer with tests.
3. `utils/toolkit_blueprint_enrichment.py` - new patch validator and no-provider dry path first; add provider orchestration after tests.
4. `web/extensions/toolkit_homebrew_packet_builder.py` - route source-blueprint v2 builds to seed/enrich helper when flag enabled.
5. `web/routes/toolkit_homebrew_routes.py` - add job states and status payload fields.
6. `web/extensions/toolkit_module_finisher.py` - ensure summary generation remains final and report fields identify summary path.
7. Tests and Numillian end-to-end fixture.

## Test Strategy

Add focused tests before integration tests:

- `scripts/test_toolkit_blueprint_v2_contract.py`
- `scripts/test_toolkit_blueprint_seed_writer.py`
- `scripts/test_toolkit_blueprint_enrichment_patches.py`
- `scripts/test_toolkit_homebrew_gui_unified_flow.py`
- `scripts/test_toolkit_module_summary_finisher_contract.py`
- `scripts/test_accurate_ingest_numillian_end_to_end.py`

Use `.venv/bin/python` for all test and validation commands.

## Risks

| Risk | Mitigation |
|---|---|
| Blueprint v2 grows too large | Keep source excerpts bounded and store full source refs in artifacts |
| Seed writer creates valid but thin modules | Follow with bounded enrichment, but preserve source structure even if enrichment fails |
| LLM enrichment edits structure indirectly | Patch validator allows only explicit text fields and blueprint IDs |
| GUI job flow becomes confusing | Keep one visible flow and show source/fidelity status summaries |
| Summary output hides defects | Treat `MODULE_SUMMARY.md` as derived only; source-fidelity gates stay authoritative |
