## ADDED Requirements

### Requirement: Monster Materialization Report Is Deterministic

The materialization step SHALL produce deterministic report metadata for source monster and encounter handling.

#### Scenario: Report includes count categories
- **GIVEN** monster materialization runs for a source-enhanced build
- **WHEN** the report is written or returned
- **THEN** it SHALL include counts for planned, reused, generated, skipped, unresolved, encounters planned, and encounters bound
- **AND** repeated runs with the same inputs SHALL produce stable counts and ordering.

#### Scenario: Report preserves evidence references
- **GIVEN** source refs include source evidence keys or artifact paths
- **WHEN** materialization diagnostics are produced
- **THEN** report entries SHALL preserve compact evidence references
- **AND** the report SHALL NOT copy full raw source bodies.

#### Scenario: Report does not override publication gates
- **GIVEN** materialization reports success or degraded status
- **WHEN** readiness, validation, benchmark, or publishability gates run
- **THEN** those gates SHALL remain authoritative for their domains
- **AND** the materialization report SHALL NOT mark a module publishable by itself.

### Requirement: Unresolved Critical Refs Remain Visible

Unresolved source monster refs SHALL remain visible to later audit and builder workflows.

#### Scenario: Critical unresolved ref survives report refresh
- **GIVEN** a required source monster ref is unresolved
- **WHEN** toolkit reports are composed
- **THEN** the unresolved ref SHALL remain visible in machine-readable report fields
- **AND** it SHALL NOT be hidden by summary markdown generation.

## SHOULD Guidance

Keep the report compact and builder-readable. Prefer artifact paths and evidence keys over large embedded text.
