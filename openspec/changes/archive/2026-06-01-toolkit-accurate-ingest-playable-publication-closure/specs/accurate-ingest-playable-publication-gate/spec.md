## ADDED Requirements

### Requirement: GUI Accurate-Ingest Builds Publish Only When Playable

The web GUI Module Builder accurate-ingest flow MUST mark a module playable/published only when source fidelity, validation, topology, artifact cleanliness, and publishability gates all pass.

#### Scenario: Source fidelity passes but validation fails
- **GIVEN** an accurate-ingest module has source_fidelity_status `pass`
- **AND** validation has schema or topology failures
- **WHEN** the GUI build reaches final status
- **THEN** the module SHALL NOT be marked playable or published
- **AND** the status payload SHALL identify validation/topology as the blocker class.

#### Scenario: All gates pass
- **GIVEN** source fidelity, validation, topology, artifact cleanliness, and publishability all pass
- **WHEN** the GUI build completes
- **THEN** the module SHALL be eligible for gameplay testing from Start Game.

### Requirement: Playable Status Uses Report Agreement

Playable status MUST be derived from current report artifacts generated from live module JSON.

#### Scenario: Reports disagree
- **GIVEN** benchmark report says pass
- **AND** toolkit build report or publishability report says blocked
- **WHEN** final GUI status is computed
- **THEN** playable status SHALL be blocked
- **AND** stale or contradictory report fields SHALL be surfaced as diagnostics.
