# accurate-ingest-builder-audit-brief-inputs Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-builder-audit-briefing. Update Purpose after archive.
## Requirements
### Requirement: Brief Generator SHALL load an existing audit run

The builder audit brief generator SHALL consume an existing backstage audit run directory containing the four required audit artifacts.

Required artifacts SHALL be:

- `run.json`
- `evidence.json`
- `audit_report.json`
- `recommendation.json`

#### Scenario: Required artifacts are loaded

- **GIVEN** a run directory containing the four required audit artifacts
- **WHEN** the brief generator runs
- **THEN** it SHALL parse all four artifacts as JSON
- **AND** it SHALL include their source paths in briefing metadata.

#### Scenario: Missing artifact fails clearly

- **GIVEN** a run directory missing a required audit artifact
- **WHEN** the brief generator runs
- **THEN** it SHALL fail with a clear missing-artifact error
- **AND** it SHALL NOT produce partial briefing outputs.

### Requirement: Brief Generator SHALL validate task identity

The brief generator SHALL verify that the audit artifacts refer to the same audit task before producing output.

#### Scenario: Task IDs match

- **GIVEN** `run.json`, `audit_report.json`, and `recommendation.json` contain the same `task_id`
- **WHEN** the brief generator validates inputs
- **THEN** validation SHALL pass.

#### Scenario: Task ID mismatch blocks output

- **GIVEN** required artifacts contain inconsistent task IDs
- **WHEN** the brief generator validates inputs
- **THEN** it SHALL fail with a task-identity error
- **AND** it SHALL NOT write briefing outputs.

