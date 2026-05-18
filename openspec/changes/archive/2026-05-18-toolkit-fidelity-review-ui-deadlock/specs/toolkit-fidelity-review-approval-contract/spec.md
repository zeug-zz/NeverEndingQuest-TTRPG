## ADDED Requirements

### Requirement: Backend fidelity approval SHALL remain strict

The backend SHALL remain authoritative for whether a fidelity review can be approved.

#### Scenario: Non-approvable review cannot be approved

- **GIVEN** a fidelity review payload fails `can_approve_fidelity_review(...)`
- **WHEN** the frontend submits an approve decision
- **THEN** the backend SHALL reject the request with `fidelity_review_not_approvable`
- **AND** the backend SHALL include the current fidelity review payload in the error response.

#### Scenario: Stale blocker signature cannot be approved

- **GIVEN** the operator submits an approve decision with a stale blocker signature
- **WHEN** the backend compares the submitted signature with the current review signature
- **THEN** the backend SHALL reject the request with `fidelity_review_stale`.

#### Scenario: Missing fidelity state cannot be approved

- **GIVEN** an accurate-ingest approval request omits required fidelity signatures
- **WHEN** the backend validates the request
- **THEN** the backend SHALL reject the request with `fidelity_review_state_missing`.

### Requirement: UI fixes SHALL NOT introduce broad force approval

The implementation SHALL NOT add a broad frontend or backend force-approval path that bypasses blocker, failed-status, missing-artifact, stale-signature, or unready-blueprint checks.

#### Scenario: Blocked fidelity review remains blocked

- **GIVEN** a fidelity review has status `blocked` or contains blockers
- **WHEN** the operator views the review UI
- **THEN** the UI MAY show reject and refresh controls
- **AND** the UI SHALL NOT submit a successful approval bypass for that blocked review.

#### Scenario: Blueprint not ready remains non-approvable

- **GIVEN** a fidelity review has `blueprint.status != "ready"`
- **WHEN** the operator views the review UI
- **THEN** the UI SHALL explain that blueprint readiness prevents approval
- **AND** the backend SHALL continue to reject approval until the blueprint becomes ready.
