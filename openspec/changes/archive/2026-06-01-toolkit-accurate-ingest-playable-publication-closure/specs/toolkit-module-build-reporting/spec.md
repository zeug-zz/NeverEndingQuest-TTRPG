## MODIFIED Requirements

### Requirement: Toolkit Report Surfaces Next Action By Blocker Class

Toolkit build reports MUST include blocker-class routing for accurate-ingest publication failures.

#### Scenario: Module is not playable after source-fidelity pass
- **GIVEN** source fidelity passes
- **AND** validation or topology fails
- **WHEN** the toolkit report is written
- **THEN** the report SHALL preserve source_fidelity_status `pass`
- **AND** it SHALL list validation/topology as the next-action blocker class.
