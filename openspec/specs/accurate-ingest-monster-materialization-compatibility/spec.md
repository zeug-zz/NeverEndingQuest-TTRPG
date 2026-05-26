# Accurate-Ingest Monster Materialization Compatibility

## Purpose

Ensure legacy concept builds and accurate-ingest jobs without source monster refs remain compatible and do not emit false monster blockers.

## Requirements

### Requirement: Legacy And No-Source Paths Remain Compatible

Monster materialization SHALL be inactive or no-op-compatible for legacy concept builds and accurate-ingest jobs without source monster refs.

#### Scenario: Legacy concept build has no source refs
- **GIVEN** a normal concept ModuleBuilder build has no source-enhanced monster refs
- **WHEN** the build path runs
- **THEN** monster materialization SHALL NOT emit false unresolved source-monster blockers
- **AND** existing concept-builder behavior SHALL remain functional.

#### Scenario: Accurate-ingest build has no monster refs
- **GIVEN** a source-enhanced accurate-ingest build has no source monster refs or encounter seeds
- **WHEN** materialization runs
- **THEN** it SHALL return a pass or skipped no-op status
- **AND** it SHALL NOT create empty blocker artifacts.

#### Scenario: Tests avoid provider and production rebuild dependencies
- **GIVEN** the materialization test suite runs in CI or local development
- **WHEN** tests execute
- **THEN** they SHALL NOT call live LLM providers
- **AND** they SHALL NOT require a production Numillian rebuild
- **AND** they SHALL use temp fixtures or isolated workspaces for artifact writes.

### Requirement: Existing Gates Are Not Weakened

The materialization change SHALL not weaken source-fidelity, build-fidelity, validation, readiness, or publishability gates.

#### Scenario: Existing benchmark remains unchanged
- **GIVEN** this change is applied
- **WHEN** Numillian benchmark tests run
- **THEN** benchmark thresholds, fixture data, and scanner logic SHALL remain unchanged unless a later dedicated OpenSpec change authorizes it.

## SHOULD Guidance

Prefer compatibility tests around existing accurate-ingest GUI and blueprint suites rather than broad end-to-end rebuilds in this slice.
