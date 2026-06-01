## MODIFIED Requirements

### Requirement: Build Fidelity Gate Composes Playable Readiness

The toolkit build fidelity gate MUST distinguish source-fidelity pass from playable-publication pass.

#### Scenario: Source fidelity passes but schema fails
- **GIVEN** source-fidelity categories all pass
- **AND** schema validation fails
- **WHEN** build fidelity status is surfaced
- **THEN** source_fidelity_status MAY be `pass`
- **AND** playable/publication status SHALL be blocked.
