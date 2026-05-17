## ADDED Requirements

### Requirement: Normalization reports SHALL expose compact fidelity status

The normalizer SHALL add compact fidelity and repair status fields to `normalization_report.json` without duplicating full report artifacts.

#### Scenario: Clean fidelity status

- **GIVEN** fidelity audit runs successfully
- **AND** no blocking findings remain
- **WHEN** normalization report is persisted
- **THEN** it SHALL include fidelity status, blocking count, warning count, covered required count, and total required count.

#### Scenario: Repaired fidelity status

- **GIVEN** fidelity audit finds blocking repairable issues
- **AND** repair succeeds
- **WHEN** normalization report is persisted
- **THEN** it SHALL include repair attempted status, repair success status, repair attempt count, and final fidelity status.

### Requirement: Fidelity artifacts SHALL be workspace-local and reviewable

The toolkit SHALL persist detailed fidelity and repair artifacts under the active upload workspace when available.

#### Scenario: Workspace available

- **GIVEN** a workspace path is available
- **WHEN** fidelity audit and repair run
- **THEN** `normalization_fidelity_report.json`, `normalization_repair_report.json`, and repair attempt artifacts SHALL be written atomically where practical.

#### Scenario: Workspace unavailable

- **GIVEN** fidelity helpers run without a workspace path
- **WHEN** report persistence is unavailable
- **THEN** helpers SHALL return structured in-memory results
- **AND** they SHALL NOT crash solely because artifact persistence is unavailable.

### Requirement: Fidelity readiness SHALL distinguish clean, degraded, repairable, and failed states

Fidelity status SHALL be explicit enough for later readiness gates and review UI surfaces to distinguish outcomes.

#### Scenario: Blocking unrepairable finding remains

- **GIVEN** fidelity audit finds a required source atom missing from the packet
- **AND** the finding is not safely repairable in this slice
- **WHEN** final fidelity status is computed
- **THEN** status SHALL be `failed` or `blocked`
- **AND** readiness consumers SHALL be able to surface the blocker class.

#### Scenario: Audit skipped due missing source artifacts

- **GIVEN** fidelity audit cannot run because source artifacts are missing
- **WHEN** final fidelity status is computed
- **THEN** status SHALL be `degraded`
- **AND** it SHALL NOT be reported as clean.
