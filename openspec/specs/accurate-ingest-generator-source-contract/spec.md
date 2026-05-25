## Purpose

Define the source-enhanced generator context contract so accurate-ingest builds inject bounded source fields before ModuleBuilder sub-generator creative generation, while legacy builds remain unaffected.

## Requirements

### Requirement: Source-Enhanced Generator Context

Source-enhanced accurate-ingest builds SHALL provide generator-visible source context before any ModuleBuilder sub-generator performs creative LLM generation.

#### Scenario: Source context is available to ModuleBuilder

- **GIVEN** an accurate-ingest v2 workspace with ready source blueprint artifacts
- **WHEN** the packet builder routes through the source-enhanced ModuleBuilder path
- **THEN** the builder input SHALL include source context fields for NPCs, locations, puzzles, tone, source locks, and source artifact paths
- **AND** ModuleBuilder SHALL be able to consume that context without requiring live provider calls in tests.

#### Scenario: Legacy build has no source context requirement

- **GIVEN** a non-source concept builder request
- **WHEN** ModuleBuilder runs
- **THEN** it SHALL remain functional without source blueprint fields
- **AND** it SHALL NOT inherit stale source context from any accurate-ingest workspace.

### Requirement: Source Lock Guidance

Generator-visible source context SHALL include explicit guidance that source names, source plot topology, puzzle rules, and major source entities must not be replaced by unsupported inventions.

#### Scenario: Source locks are present

- **GIVEN** source-enhanced builder input
- **WHEN** source context is serialized for generators
- **THEN** it SHALL include rules forbidding replacement plotlines, invented major entities, source name drift, and puzzle rule rewrites.
