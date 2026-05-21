## ADDED Requirements

### Requirement: Seed writer SHALL require explicit fallback or preview enablement

The deterministic seed writer SHALL NOT run as the default accurate-ingest GUI authoring path.

#### Scenario: Default path blocks seed writer

- **GIVEN** `ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD` is false
- **AND** `ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK` is false
- **AND** no explicit request-level preview/fallback state is present
- **WHEN** an accurate-ingest packet build starts
- **THEN** the seed-writer executor SHALL NOT run.

#### Scenario: Explicit fallback may use seed writer

- **GIVEN** seed-writer fallback is explicitly enabled by configuration or request state
- **WHEN** the accurate-ingest build cannot or should not use ModuleBuilder
- **THEN** the seed-writer executor MAY run
- **AND** the result SHALL be labelled as seed fallback, seed preview, or seed support rather than normal ModuleBuilder authoring.

### Requirement: Seed writer status SHALL not imply full authored adventure quality

Seed-writer output SHALL report seed-specific status and mode semantics so structure-only output is not mistaken for a source-enhanced ModuleBuilder adventure.

#### Scenario: Seed fallback result labelled honestly

- **GIVEN** an explicit seed-writer fallback build runs
- **WHEN** build metadata is persisted
- **THEN** the metadata SHALL include a seed-specific build mode
- **AND** downstream reports SHALL be able to distinguish it from default ModuleBuilder output.
