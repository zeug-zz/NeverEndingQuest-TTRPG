# Design: Accurate-Ingest Seed Writer Completion

## Overview

This change strengthens the deterministic materialization step in the accurate-ingest pipeline. The seed writer sits after `builder_blueprint.v2` validation and before any LLM enrichment. It is the point where source truth becomes schema-valid NEQ module files.

The design preserves the existing helper entry point:

```python
materialize_module_from_blueprint(
    blueprint: Dict[str, Any],
    module_dir: str,
    overwrite: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]
```

No provider calls are allowed in this layer.

## Decision 1: Seed Files Are Toolkit Support Artifacts

`npcs_seed.json` and `monsters_seed.json` SHALL be emitted as support artifacts for downstream media prewarm, monster materialization, MMG authority, and publication workflows.

They SHOULD not be treated as gameplay runtime truth. Runtime truth remains module context, area files, encounter files, and character/NPC records.

Suggested `npcs_seed.json` shape:

```json
{
  "schema_version": "toolkit_npc_seed.v1",
  "source": "builder_blueprint.v2",
  "blueprint_version": "source_faithful_builder_blueprint.v2",
  "npcs": []
}
```

Suggested `monsters_seed.json` shape:

```json
{
  "schema_version": "toolkit_monster_seed.v1",
  "source": "builder_blueprint.v2",
  "blueprint_version": "source_faithful_builder_blueprint.v2",
  "monsters": []
}
```

## Decision 2: Source Metadata Belongs In A Seed Source Report When Schemas Cannot Hold It

Module schemas can be strict. The seed writer SHALL preserve source refs, blueprint IDs, original source names, and source order either in schema-valid module fields or in a sidecar report.

Recommended sidecar:

```text
seed_source_report.json
```

Suggested report shape:

```json
{
  "report_version": "toolkit_seed_source_report.v1",
  "source": "builder_blueprint.v2",
  "module_title": "...",
  "source_hash": "...",
  "locations": [],
  "npcs": [],
  "plot_beats": [],
  "puzzles": [],
  "items": [],
  "monsters": []
}
```

## Decision 3: Write Results Must Be Severity Classified

The current helper records `created_files` and `skipped_files`. This change SHALL add severity-aware result classification.

Required canonical writes include:

- `module_context.json`
- `module_context_BU.json`
- `module_plot.json`
- `module_plot_BU.json`
- at least one `areas/*_BU.json` for non-empty blueprints
- corresponding runtime area JSON if current toolkit conventions require it
- map JSON for areas with map data
- `npcs_seed.json`
- `monsters_seed.json`
- `seed_source_report.json`

If any required canonical write fails, the result MUST NOT be `seed_status: success`.

Optional write failures SHOULD degrade rather than fail if the module remains valid and publication gates can surface the missing artifact.

## Decision 4: Monster Seeding Is Conservative

This slice SHALL NOT generate monster stat files. It SHALL only preserve source monster references and materialization hints for later tooling.

Monster seed extraction SHOULD use, in priority order:

1. `encounter_plan` explicit monster/creature entries.
2. Source graph or blueprint monster atoms if available.
3. Structured location monster refs if present.
4. Normalized packet monster hints if present.

Entries should include enough metadata for later materialization without inventing stat blocks.

## Decision 5: No Route Or Finisher Rewrites In This Slice

This slice SHOULD avoid route and finisher changes. GUI overwrite confirmation and final publication wiring are separate OpenSpec changes.

If a caller change is necessary, it MUST be minimal and preserve legacy behavior when blueprint-native build is disabled.

## Migration And Rollback

Migration is additive. Existing blueprint-native builds will gain support artifacts and stricter failure semantics.

Rollback is safe: remove new support artifact generation and tests. Existing core file generation remains unchanged.

## Verification Strategy

Use provider-free unit tests and temporary directories. Do not rely on live Numillian module mutation for this slice.

Required checks:

```bash
.venv/bin/python -m py_compile utils/toolkit_blueprint_seed_writer.py scripts/test_toolkit_blueprint_seed_writer.py
.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_seed_writer
openspec validate toolkit-accurate-ingest-seed-writer-completion
```
