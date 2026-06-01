## ADDED Requirements

### Requirement: Reports Agree Before Playable Completion

Benchmark, source-fidelity, toolkit build, validation, and publishability reports MUST agree before a GUI build is marked playable.

#### Scenario: Toolkit report carries stale blocked categories
- **GIVEN** source-fidelity report says pass
- **AND** toolkit report category details still show missing required content
- **WHEN** final status is computed
- **THEN** the build SHALL be blocked as report-inconsistent
- **AND** the GUI SHALL show a report refresh/consistency action.

### Requirement: Report Refresh Order Is Deterministic

Report refresh MUST happen in dependency order so downstream reports consume current upstream results.

#### Scenario: Source fidelity changes after repair
- **GIVEN** a repair changes live module JSON
- **WHEN** finalization refreshes reports
- **THEN** source-fidelity outputs SHALL refresh before toolkit and publishability reports
- **AND** toolkit/publishability reports SHALL consume the refreshed source-fidelity state.
