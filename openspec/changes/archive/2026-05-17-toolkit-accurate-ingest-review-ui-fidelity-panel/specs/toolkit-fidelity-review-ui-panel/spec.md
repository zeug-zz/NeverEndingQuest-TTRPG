## ADDED Requirements

### Requirement: Toolkit UI SHALL render source fidelity review state

The Homebrew toolkit UI SHALL display source fidelity review state before accurate-ingest build approval.

#### Scenario: Fidelity panel displays summary

- **GIVEN** the review API returns a `fidelity_review` payload
- **WHEN** the Homebrew upload review/status UI renders
- **THEN** it SHALL display fidelity status, blocker count, warning count, repair attempt count, and blueprint readiness.

#### Scenario: Fidelity panel displays source coverage

- **GIVEN** the review payload includes coverage counts by source atom category
- **WHEN** the panel renders
- **THEN** it SHALL display required NPC, location, plot, puzzle, clue, encounter, item, and tone coverage where available.

#### Scenario: Approval action is disabled for blockers

- **GIVEN** `fidelity_review.can_approve` is false
- **WHEN** the UI renders approval/build controls
- **THEN** it SHALL disable or hide approval/build actions
- **AND** it SHALL show the refusal reason.

### Requirement: Fidelity panel SHALL preserve legacy UI behavior

The fidelity panel SHALL be additive and SHALL NOT break existing legacy upload review or build controls.

#### Scenario: Legacy review omits fidelity panel

- **GIVEN** the review API does not include an accurate-ingest fidelity review payload
- **WHEN** the Homebrew toolkit UI renders
- **THEN** existing review/build controls SHALL continue to render as before.
