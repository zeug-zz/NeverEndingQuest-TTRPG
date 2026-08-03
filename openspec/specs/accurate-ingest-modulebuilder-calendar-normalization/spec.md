# accurate-ingest-modulebuilder-calendar-normalization Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-modulebuilder-structural-repair. Update Purpose after archive.
## Requirements
### Requirement: Accurate-Ingest Normalizes Party Calendar Before Validation

Accurate-ingest ModuleBuilder builds SHALL normalize or reject party tracker calendar values before final validation and final-editor routing.

#### Scenario: Known invalid month is normalized
- **GIVEN** generated `party_tracker_BU.json` or equivalent canonical party artifact contains a known invalid month such as `Hammer`
- **WHEN** the calendar normalization stage runs
- **THEN** the month SHALL be rewritten to a schema-valid value or explicitly cleared according to the existing party schema contract
- **AND** the normalization report SHALL record the original value and normalized value.

#### Scenario: Unknown invalid month fails closed
- **GIVEN** generated party calendar data contains an invalid month that cannot be normalized safely
- **WHEN** calendar normalization runs
- **THEN** the build SHALL be blocked with an explicit party calendar diagnostic
- **AND** final-editor reconciliation SHALL NOT be invoked for that build.

#### Scenario: Prompt seed no longer emits known invalid calendar month
- **GIVEN** generator prompts include party tracker or location examples
- **WHEN** source-contract tests inspect those prompts
- **THEN** they SHALL NOT include `"month": "Hammer"` as a valid example.

### Requirement: Calendar Normalization Is Build-Time Only

Calendar normalization for accurate-ingest structural repair SHALL operate on build artifacts, not live campaign runtime state.

#### Scenario: Runtime files are not edited
- **GIVEN** the structural repair stage normalizes calendar data
- **WHEN** it writes changes
- **THEN** it SHALL target canonical build artifacts only
- **AND** it SHALL NOT edit runtime-only `party_tracker.json` as part of publication repair.

