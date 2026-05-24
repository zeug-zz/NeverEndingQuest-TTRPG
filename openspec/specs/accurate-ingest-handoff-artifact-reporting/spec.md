# accurate-ingest-handoff-artifact-reporting

## Purpose

Ensure accurate-ingest packet builds report sufficient metadata for operators and tests to distinguish ModuleBuilder handoff from seed writer support modes, including on failure.

## Requirements

### Requirement: Build results SHALL report handoff mode and artifacts

Accurate-ingest packet builds SHALL report enough metadata for operators and tests to distinguish ModuleBuilder handoff from seed writer support modes.

#### Scenario: ModuleBuilder handoff reports builder artifacts

- **GIVEN** a default source-enhanced ModuleBuilder build
- **WHEN** the packet builder returns success
- **THEN** the result SHALL include `build_mode`
- **AND** `builder_input_path`
- **AND** `build_result_path`
- **AND** module name or output directory metadata.

#### Scenario: Seed writer support reports seed mode

- **GIVEN** an explicit seed writer build
- **WHEN** the packet builder returns success
- **THEN** the result SHALL include `build_mode`
- **AND** `seed_writer_mode`
- **AND** seed writer coverage or seed status metadata.

### Requirement: Handoff artifacts SHALL remain auditable after failure

If ModuleBuilder execution fails after handoff persistence, the build result SHALL still report the handoff artifact path when available.

#### Scenario: ModuleBuilder failure preserves handoff path

- **GIVEN** ModuleBuilder raises during execution
- **WHEN** the packet builder returns a failed result
- **THEN** the result SHALL include `builder_input_path` and `build_result_path` when those artifacts were created.
