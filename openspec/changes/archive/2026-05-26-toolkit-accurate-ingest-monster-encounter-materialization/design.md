# Design: Accurate-Ingest Monster Encounter Materialization

## Contract Layer (MUST)

### Architecture Boundary

This change SHALL run after source-enhanced handoff/generator source locks and before final publication proof. It SHALL not replace the existing ModuleBuilder orchestration.

The materialization boundary is:

```text
source_monster_refs + source_encounter_seeds
  -> deterministic reuse-first resolver
  -> module-local monster artifacts or unresolved diagnostics
  -> encounter seed/plan bindings
  -> report metadata
```

### Truth Sources

- Source-enhanced `builder_input` and related accurate-ingest artifacts SHALL provide source refs and encounter seeds.
- Existing module/SRD/bestiary-compatible monster templates SHALL provide stat data when reusable.
- Generated module reports SHALL record what happened; reports SHALL NOT create source truth.

### Failure Semantics

- Unambiguous reusable monster refs SHALL materialize into module-local monster artifacts.
- Ambiguous or missing monster refs SHALL be recorded as unresolved diagnostics.
- Required write or schema failures SHALL return degraded/failed materialization status and SHALL NOT be hidden by later report success.
- Encounter seeds with unambiguous monster refs SHALL carry canonical monster bindings.
- Encounter seeds with unresolved refs SHALL remain present with unresolved diagnostics rather than dropping the monster context.

### Compatibility

- Legacy concept builds SHALL behave as before when no source-enhanced monster refs are present.
- Accurate-ingest paths with no monster refs SHALL not produce false blockers.
- Tests SHALL avoid provider calls and production Numillian rebuilds.

## Guidance Layer (SHOULD)

### Preferred Implementation Shape

Prefer a compact helper such as `utils/accurate_ingest_monster_materialization.py` if existing helper boundaries become awkward. The helper can expose a pure function that accepts:

- `module_dir`
- `source_monster_refs`
- `source_encounter_seeds`
- optional `module_slug` or source metadata

and returns a report dictionary with:

- `status`
- `monsters_planned`
- `monsters_reused`
- `monsters_generated`
- `monsters_unresolved`
- `encounters_planned`
- `encounters_bound`
- `unresolved_refs`
- `artifact_paths`

### Reuse-First Resolution

Prefer existing data sources in this order when practical:

1. Existing module-local `monsters/*.json`.
2. Existing project bestiary/template data used by module monster hydration.
3. Existing generator/hydration helpers that create schema-valid monster artifacts from known templates.
4. Unresolved diagnostic when no safe reuse path exists.

Do not synthesize a made-up stat block solely from a source name in this slice.

### Report Integration

Start with a standalone materialization report and narrow `toolkit_build_report.json` metadata only if needed. Avoid broad publishability precedence changes in this change.

### Testing Strategy

Use temp module directories and small fixture inputs. Include Numillian-like refs in tests, but do not write production Numillian artifacts. Add compatibility tests proving legacy/no-source paths do not emit blockers.

### Rollout

Implement in two passes:

1. Source/report contract and provider-free tests.
2. Reuse-first artifact writes and encounter binding behavior.
