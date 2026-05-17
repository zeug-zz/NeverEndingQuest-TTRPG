## ADDED Requirements

### Requirement: Accurate-ingest jobs SHALL pause for review after normalization

When fidelity review is enabled, accurate-ingest jobs SHALL not auto-approve or auto-start build immediately after normalization succeeds.

#### Scenario: Accurate-ingest normalization pauses before build

- **GIVEN** normalization succeeds for an accurate-ingest workspace
- **WHEN** the upload pipeline reaches the review boundary
- **THEN** the job SHALL be left in a reviewable state
- **AND** packet build SHALL NOT start automatically.

#### Scenario: Legacy normalization preserves existing auto-build behavior

- **GIVEN** normalization succeeds for a legacy workspace
- **WHEN** fidelity review is disabled or not applicable
- **THEN** existing auto-approve/build behavior SHALL remain available.

### Requirement: Approval and build start SHALL fail closed while blockers remain

The toolkit SHALL prevent review approval and build start when source-fidelity blockers remain.

#### Scenario: Approval rejects blocker state

- **GIVEN** a fidelity review payload has `can_approve: false`
- **WHEN** the user submits an approve decision
- **THEN** the route SHALL return a conflict response
- **AND** it SHALL NOT persist an approved review snapshot.

#### Scenario: Build start rechecks fidelity eligibility

- **GIVEN** a job was previously reviewable
- **AND** current artifacts now show blocker findings
- **WHEN** build start is requested
- **THEN** build start SHALL fail before packet builder invocation.
