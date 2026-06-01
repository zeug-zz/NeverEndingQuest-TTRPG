## ADDED Requirements

### Requirement: Party Tracker Defaults Are Schema-Valid

Accurate-ingest finalization MUST emit schema-valid `party_tracker_BU.json` defaults.

#### Scenario: Source uses unsupported calendar names
- **GIVEN** source or generated content proposes a month value outside the party tracker schema enum
- **WHEN** finalization writes `party_tracker_BU.json`
- **THEN** the month SHALL be normalized to a schema-valid value
- **AND** validation SHALL NOT fail on worldConditions.month.

### Requirement: Normalization Is Deterministic

Party tracker schema normalization MUST be deterministic and provider-free.

#### Scenario: Builder output omits or invents date fields
- **GIVEN** Builder output has missing or unsupported world date fields
- **WHEN** normalization runs
- **THEN** defaults SHALL be stable and schema-valid
- **AND** the normalized fields SHALL be recorded in the toolkit report diagnostics.
