## ADDED Requirements

### Requirement: Accepted reconciliation SHALL create an effective source-fidelity status

When final reconciliation accepts editorial blockers, the system SHALL expose an effective source-fidelity status distinct from the original source-fidelity status.

#### Scenario: Reconciled source fidelity is not clean pass

- **GIVEN** source-fidelity status is blocked or degraded
- **AND** final reconciliation accepts the editorial blockers
- **WHEN** final status is reported
- **THEN** `source_fidelity_status` SHALL preserve the original blocked or degraded status
- **AND** `source_fidelity_effective_status` SHALL be `reconciled_degraded` or equivalent accepted reconciliation status
- **AND** the report SHALL NOT claim clean source-fidelity pass.

#### Scenario: Clean source fidelity remains pass

- **GIVEN** source-fidelity status is pass
- **AND** final reconciliation is not required
- **WHEN** final status is reported
- **THEN** `source_fidelity_effective_status` SHALL be pass or omitted as not required
- **AND** playable publication SHALL still depend on validation/readiness/publishability gates.

### Requirement: Report agreement SHALL consume accepted reconciliation status

Report agreement composition SHALL allow playable publication when accepted final reconciliation exists, original source fidelity is blocked or degraded, and all deterministic publication gates pass.

#### Scenario: Accepted reconciliation permits playable publication

- **GIVEN** validation_status=pass, ready_status=pass, publishable_status=pass, and effective_publishable_status=pass
- **AND** source_fidelity_status=blocked
- **AND** source_fidelity_effective_status=reconciled_degraded from an accepted final reconciliation report
- **WHEN** report agreement is composed
- **THEN** playable_publication_status SHALL be pass
- **AND** report agreement SHALL preserve source-fidelity diagnostics as warnings or reconciliation notes.

#### Scenario: Blocked source fidelity without reconciliation blocks publication

- **GIVEN** validation_status=pass, ready_status=pass, publishable_status=pass, and effective_publishable_status=pass
- **AND** source_fidelity_status=blocked
- **AND** no accepted final reconciliation report exists
- **WHEN** report agreement is composed
- **THEN** playable_publication_status SHALL be blocked.
