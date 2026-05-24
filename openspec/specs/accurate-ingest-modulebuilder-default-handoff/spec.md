# accurate-ingest-modulebuilder-default-handoff

## Purpose

Ensure that accurate-ingest GUI builds with valid source-blueprint artifacts route through ModuleBuilder by default, while non-source legacy builds remain compatible and blueprint-not-ready states fail closed.

## Requirements

### Requirement: Accurate-ingest default builds SHALL use ModuleBuilder

When an accurate-ingest GUI build has valid source-blueprint artifacts and no explicit seed writer mode, the packet builder SHALL route the build through existing ModuleBuilder orchestration.

#### Scenario: Default v2 accurate-ingest build uses ModuleBuilder

- **GIVEN** an approved accurate-ingest workspace with ready or degraded v2 source-blueprint artifacts
- **AND** no `seed_writer_mode` is supplied
- **WHEN** the packet builder runs
- **THEN** `_execute_module_builder(...)` SHALL be called
- **AND** `_execute_seed_writer_build(...)` SHALL NOT be called
- **AND** build mode SHALL be reported as `source_enhanced_modulebuilder`.

#### Scenario: Non-source legacy build remains compatible

- **GIVEN** a valid packet workspace without accurate-ingest source-blueprint artifacts
- **WHEN** the packet builder runs
- **THEN** existing ModuleBuilder-compatible behavior SHALL continue without requiring source-blueprint metadata.

### Requirement: Blueprint-not-ready states SHALL fail closed

If accurate-ingest source-blueprint artifacts are present but not ready for ModuleBuilder handoff, the packet builder SHALL fail before invoking ModuleBuilder.

#### Scenario: Blocked blueprint does not invoke ModuleBuilder

- **GIVEN** a workspace with blocked or malformed blueprint artifacts
- **WHEN** the packet builder runs without explicit seed writer mode
- **THEN** the build SHALL return a failed result with `blueprint_not_ready` or equivalent reason
- **AND** ModuleBuilder SHALL NOT be invoked.
