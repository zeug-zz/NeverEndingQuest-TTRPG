## MODIFIED Requirements

### Requirement: Build fidelity gate SHALL fail closed on fatal source or structure loss

Accurate-ingest builds SHALL NOT proceed to post-build finishing/publication when generated module output has fatal structural loss. Build-fidelity source preservation blockers that are classified as editorial SHALL route to final reconciliation instead of immediately blocking finishing/publication.

#### Scenario: Missing required NPC routes through final classification

- **GIVEN** the source graph or blueprint marks an NPC as required
- **AND** the generated module does not contain that NPC or an approved canonical equivalent
- **WHEN** build fidelity gates run
- **THEN** final blocker classification SHALL decide whether the missing NPC is fatal or editorial
- **AND** fatal classification SHALL block before finishing/publication
- **AND** editorial classification SHALL produce final reconciliation evidence instead of immediate terminal build failure.

#### Scenario: Missing keyed location routes through final classification

- **GIVEN** the source graph or blueprint marks a location as required
- **AND** the generated module omits that location or replaces it with unsupported invented structure
- **WHEN** build fidelity gates run
- **THEN** final blocker classification SHALL decide whether the missing location is fatal or editorial
- **AND** fatal classification SHALL block before finishing/publication
- **AND** editorial classification SHALL produce final reconciliation evidence instead of immediate terminal build failure.

#### Scenario: Replacement plot topology blocks finishing when fatal

- **GIVEN** source topology defines required plot beats, trials, puzzle rules, or clue dependencies
- **AND** generated module output replaces or omits that topology
- **WHEN** build fidelity gates run
- **THEN** fatal topology loss SHALL block finishing/publication
- **AND** editorial topology mismatch SHALL route to final reconciliation
- **AND** the report SHALL include a compact blocker reason and classification.

### Requirement: Build fidelity gate SHALL preserve pass-through behavior when non-blocking

The toolkit SHALL continue existing finishing/publication flow when accurate-ingest build fidelity is passing, warning-only, or editorial-only with accepted final reconciliation.

#### Scenario: Passing report continues finishing

- **GIVEN** build fidelity report status is `pass`
- **WHEN** packet builder integration handles the report
- **THEN** existing finishing/publication handoff SHALL continue.

#### Scenario: Disabled gate preserves current behavior

- **GIVEN** `ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES` is disabled
- **WHEN** packet build completes
- **THEN** build fidelity gates SHALL NOT block existing behavior.

#### Scenario: Editorial-only blocker with accepted reconciliation continues finishing

- **GIVEN** build fidelity report status is `blocked`
- **AND** all blockers are classified as editorial
- **AND** accepted final reconciliation exists
- **WHEN** packet builder integration handles the report
- **THEN** finishing/publication handoff SHALL continue
- **AND** source-fidelity diagnostics SHALL remain attached to the result payload.
