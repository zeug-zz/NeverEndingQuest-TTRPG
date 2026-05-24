# accurate-ingest-seed-writer-explicit-support-role

## Purpose

Ensure the seed writer remains available only as explicit support tooling, not as the default accurate-ingest GUI authoring path, with invalid modes failing closed.

## Requirements

### Requirement: Seed writer SHALL require explicit support mode

The seed writer SHALL remain available only as explicit support tooling, not as the default accurate-ingest GUI authoring path.

#### Scenario: Explicit fallback mode uses seed writer

- **GIVEN** a valid accurate-ingest workspace
- **AND** `seed_writer_mode` is `fallback`
- **WHEN** the packet builder runs
- **THEN** `_execute_seed_writer_build(...)` SHALL be called
- **AND** build mode SHALL be reported as `blueprint_seed_fallback`
- **AND** `seed_writer_mode` SHALL be recorded as `fallback`.

#### Scenario: Explicit preview mode uses seed writer

- **GIVEN** a valid accurate-ingest workspace
- **AND** `seed_writer_mode` is `preview`
- **WHEN** the packet builder runs
- **THEN** `_execute_seed_writer_build(...)` SHALL be called
- **AND** build mode SHALL be reported as `blueprint_seed_preview`
- **AND** `seed_writer_mode` SHALL be recorded as `preview`.

#### Scenario: Explicit support mode uses seed writer

- **GIVEN** a valid accurate-ingest workspace
- **AND** `seed_writer_mode` is `support`
- **WHEN** the packet builder runs
- **THEN** `_execute_seed_writer_build(...)` SHALL be called
- **AND** build mode SHALL be reported as `blueprint_seed_support`
- **AND** `seed_writer_mode` SHALL be recorded as `support`.

#### Scenario: Invalid seed writer mode fails closed

- **GIVEN** an unsupported `seed_writer_mode`
- **WHEN** the packet builder runs
- **THEN** the build SHALL fail with `seed_writer_mode_invalid`
- **AND** no builder executor SHALL be invoked.
