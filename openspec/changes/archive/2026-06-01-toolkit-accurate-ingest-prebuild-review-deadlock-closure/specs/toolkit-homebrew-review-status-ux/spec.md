## MODIFIED Requirements

### Requirement: GUI Status Does Not Overstate Playability

The homebrew/accurate-ingest review UI MUST NOT imply a module is ready for gameplay testing while validation, topology, artifact, publishability, report-agreement, or playable-publication blockers remain.

#### Scenario: Accurate-ingest build completes with blockers

- **GIVEN** the build pipeline has produced module artifacts
- **AND** final playable-publication gates fail
- **WHEN** the GUI renders completion status
- **THEN** it SHALL show a blocked/not-playable status
- **AND** it SHALL provide the blocker class and recommended next action.

#### Scenario: Rejected or no-module job is not shown as success

- **GIVEN** an accurate-ingest job is `rejected`, `failed`, `blocked`, `quarantined`, or has no module folder
- **WHEN** the GUI renders status guidance
- **THEN** it SHALL NOT render the job as successful or completed for build purposes
- **AND** it SHALL NOT append MMG guidance unless a module folder exists and the build is in an MMG-eligible state.

#### Scenario: Missing blueprint is surfaced as build blocker

- **GIVEN** an accurate-ingest job cannot find or create `builder_blueprint.json`
- **WHEN** the GUI renders the job status
- **THEN** it SHALL show an explicit build-blocked or missing-artifact state
- **AND** it SHALL include `builder_blueprint` or equivalent artifact identity in diagnostics.
