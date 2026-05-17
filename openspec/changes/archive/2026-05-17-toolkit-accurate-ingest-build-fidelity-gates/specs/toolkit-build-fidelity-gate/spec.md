## ADDED Requirements

### Requirement: Build fidelity gate SHALL fail closed on critical source loss

Accurate-ingest builds SHALL NOT proceed to post-build finishing/publication when generated module output loses critical source content.

#### Scenario: Missing required NPC blocks finishing

- **GIVEN** the source graph or blueprint marks an NPC as required
- **AND** the generated module does not contain that NPC or an approved canonical equivalent
- **WHEN** build fidelity gates run
- **THEN** the build SHALL be blocked before finishing/publication
- **AND** the report SHALL identify the source atom/category and generated artifact scope.

#### Scenario: Missing keyed location blocks finishing

- **GIVEN** the source graph or blueprint marks a location as required
- **AND** the generated module omits that location or replaces it with unsupported invented structure
- **WHEN** build fidelity gates run
- **THEN** the build SHALL be blocked before finishing/publication.

#### Scenario: Replacement plot topology blocks finishing

- **GIVEN** source topology defines required plot beats, trials, puzzle rules, or clue dependencies
- **AND** generated module output replaces or omits that topology
- **WHEN** build fidelity gates run
- **THEN** the build SHALL be blocked
- **AND** the report SHALL include a compact blocker reason.

### Requirement: Build fidelity gate SHALL preserve pass-through behavior when non-blocking

The toolkit SHALL continue existing finishing/publication flow when accurate-ingest build fidelity is passing or warning-only.

#### Scenario: Passing report continues finishing

- **GIVEN** build fidelity report status is `pass`
- **WHEN** packet builder integration handles the report
- **THEN** existing finishing/publication handoff SHALL continue.

#### Scenario: Disabled gate preserves current behavior

- **GIVEN** `ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES` is disabled
- **WHEN** packet build completes
- **THEN** build fidelity gates SHALL NOT block existing behavior.
