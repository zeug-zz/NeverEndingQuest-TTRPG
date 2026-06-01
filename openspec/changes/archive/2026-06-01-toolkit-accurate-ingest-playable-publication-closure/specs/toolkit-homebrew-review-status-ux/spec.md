## MODIFIED Requirements

### Requirement: GUI Status Does Not Overstate Playability

The homebrew/accurate-ingest review UI MUST NOT imply a module is ready for gameplay testing while validation, topology, artifact, or publishability blockers remain.

#### Scenario: Accurate-ingest build completes with blockers
- **GIVEN** the build pipeline has produced module artifacts
- **AND** final playable-publication gates fail
- **WHEN** the GUI renders completion status
- **THEN** it SHALL show a blocked/not-playable status
- **AND** it SHALL provide the blocker class and recommended next action.
