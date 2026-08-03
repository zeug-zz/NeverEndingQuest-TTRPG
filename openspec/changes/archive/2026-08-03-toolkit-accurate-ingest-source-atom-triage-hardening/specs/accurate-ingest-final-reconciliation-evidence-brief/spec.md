## ADDED Requirements

### Requirement: Final reconciliation briefs SHALL carry available evidence

When editorial blockers reach the final reconciliation boundary, the persisted brief SHALL include compact source evidence and generated-module summary when those artifacts are available.

#### Scenario: Source refs populate source excerpts

- **GIVEN** an editorial blocker carries a `source_atom_id`
- **AND** the source graph contains matching `source_refs`
- **WHEN** `final_reconciliation_brief.json` is built
- **THEN** `source_excerpts` SHALL include bounded source refs/excerpts for that blocker
- **AND** the brief SHALL remain valid when no refs are available by using an empty list.

#### Scenario: Generated module summary is bounded

- **GIVEN** a module directory exists with canonical artifacts
- **WHEN** the final reconciliation brief is built or enriched
- **THEN** `generated_module_summary` SHALL include bounded counts or short summaries useful to the final editor
- **AND** it SHALL NOT embed entire module files.

#### Scenario: Patch authority is not widened by evidence enrichment

- **GIVEN** the brief includes source excerpts and generated summary
- **WHEN** the LLM final editor proposes patches
- **THEN** existing patch target validation SHALL still reject runtime-only files, source/middle artifacts, absolute paths, path traversal, and non-whitelisted surfaces.

## SHOULD Guidance

- Prefer canonical editable surfaces: `module_context.json`, `module_context_BU.json`, `module_plot_BU.json`, `areas/*_BU.json`, and `map_*.json`.
- Preserve backward-compatible empty defaults when evidence inputs are omitted.
