# continuity-semantic-finalization Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-publication-readiness-closure. Update Purpose after archive.
## Requirements
### Requirement: Accurate-ingest/ModuleBuilder finishing SHALL produce continuity block in module_context

The accurate-ingest ModuleBuilder finishing pipeline SHALL populate a `continuity` block in `module_context.json` (and BU mirror if present) using existing shared helpers from `scripts/homebrew_ingest_dev.py` (`_ensure_continuity_contract_keys`, `enrich_continuity_cross_refs`).

The result SHALL contain at minimum `continuity_version` (`"v1"`), `entry_state_variants` (with `cold_start`, `partial_context`, `late_arc`), `cross_module_refs` (array), and `standalone_fallback` (object).

#### Scenario: Existing finisher output lacks continuity

- **GIVEN** a module_context.json produced by the accurate-ingest builder without a `continuity` key
- **WHEN** the finalization helper runs
- **THEN** the `continuity` block is added to module_context.json
- **AND** it is atomically rewritten
- **AND** the BU mirror is also updated if present
- **AND** the helper returns `changed=true`

#### Scenario: Continuity already present and current

- **GIVEN** a module_context.json with a valid `continuity` block
- **WHEN** the finalization helper runs
- **THEN** no changes are written
- **AND** the helper returns `changed=false`

### Requirement: Accurate-ingest/ModuleBuilder finishing SHALL produce semantic_authority payload in module_context

The accurate-ingest ModuleBuilder finishing pipeline SHALL populate a `semantic_authority` payload in `module_context.json` using `enrich_module_semantic_authority()` from `utils/module_semantic_authority.py`.

#### Scenario: Missing semantic_authority

- **GIVEN** a module_context.json produced without a `semantic_authority` key
- **WHEN** `enrich_module_semantic_authority()` runs as part of finalization
- **THEN** the payload is added with destination phrases and NPC scene authority
- **AND** module_context.json is atomically rewritten
- **AND** the helper returns `changed=true`

#### Scenario: Fail-open on missing plot data

- **GIVEN** module_plot.json is missing or unparseable
- **WHEN** the finalization helper runs
- **THEN** it returns `status=degraded` with a warning
- **AND** does not crash the pipeline

