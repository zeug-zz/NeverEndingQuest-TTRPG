# toolkit-source-fidelity-waiver-contract Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-final-benchmark-publication-gate. Update Purpose after archive.
## Requirements
### Requirement: Degraded fidelity waiver SHALL be explicitly recorded

When an operator accepts publication of a module with degraded source fidelity, the waiver decision SHALL be recorded with module slug, timestamp, fidelity status, and operator identity.

#### Scenario: Waiver is persisted

- **GIVEN** a module has source-fidelity status degraded
- **AND** the operator accepts publication
- **WHEN** the waiver is recorded
- **THEN** it SHALL include module slug, degraded categories, timestamp, and operator identity
- **AND** it SHALL be persisted to a module-local or workspace-local waiver record.

### Requirement: Waiver SHALL NOT override blocked fidelity

A waiver SHALL only apply to `degraded` source-fidelity status. `blocked` source-fidelity SHALL NOT be waivable.

#### Scenario: Operator attempts to waive blocked fidelity

- **GIVEN** source-fidelity is blocked
- **WHEN** the operator attempts to waive
- **THEN** the waiver SHALL be rejected
- **AND** publication SHALL remain blocked.

### Requirement: Waiver SHALL NOT affect structural or semantic gates

A source-fidelity waiver SHALL only affect the source-fidelity dimension. It SHALL NOT override structural readiness or semantic publishability blockers.

#### Scenario: Module has semantic publishability blocker and degraded fidelity

- **GIVEN** source-fidelity is degraded and publishable_status is blocked
- **WHEN** the operator waives source-fidelity
- **THEN** the semantic publishability blocker SHALL still block publication
- **AND** final status SHALL remain blocked.

