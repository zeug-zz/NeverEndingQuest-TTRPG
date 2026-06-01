## ADDED Requirements

### Requirement: Semantic Audit Blockers Close Through Artifact Fixes

Semantic audit blockers SHALL be resolved by source-faithful module artifact changes or remain explicit blockers. Audit rules SHALL NOT be weakened to pass release proof.

#### Scenario: Generated phrase creates false destination debt
- **GIVEN** semantic audit reports unresolved destination phrase debt from a module plot title or description
- **WHEN** finalization closes the blocker
- **THEN** the offending module artifact text SHALL be corrected to source-faithful wording
- **AND** semantic audit SHALL no longer report that blocker
- **AND** benchmark source-fidelity SHALL remain pass.

#### Scenario: Blocker cannot be safely resolved
- **GIVEN** a semantic blocker cannot be resolved without changing source meaning
- **WHEN** finalization reports status
- **THEN** the blocker SHALL remain explicit and reviewable
- **AND** no waiver SHALL be created by default.

## SHOULD Guidance

Prefer smallest-field edits, especially generated titles or phrases that trigger false destination extraction.
