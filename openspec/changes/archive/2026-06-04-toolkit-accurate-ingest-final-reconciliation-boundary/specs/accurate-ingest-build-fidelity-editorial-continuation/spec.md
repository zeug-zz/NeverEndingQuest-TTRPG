## ADDED Requirements

### Requirement: Editorial build-fidelity blockers SHALL not immediately terminate generated builds

When ModuleBuilder succeeds and build-fidelity reports only editorial blockers, the packet builder SHALL continue into final reconciliation status handling instead of returning terminal `status: blocked` solely from build-fidelity status.

#### Scenario: Editorial blockers continue to reconciliation-required status

- **GIVEN** ModuleBuilder generation succeeded and produced a module directory
- **AND** build-fidelity reports editorial/source-fidelity blockers
- **AND** final blocker classification finds no fatal blockers
- **WHEN** the packet builder builds the result payload
- **THEN** the result SHALL include `final_reconciliation_required: true`
- **AND** it SHALL include paths to build-fidelity and final reconciliation brief artifacts
- **AND** it SHALL NOT stop solely because `source_fidelity_status` or build-fidelity status is blocked.

#### Scenario: Accepted reconciliation allows readiness and finishing to run

- **GIVEN** ModuleBuilder generation succeeded
- **AND** final blocker classification found only editorial blockers
- **AND** an accepted final reconciliation report exists for the workspace
- **WHEN** the route pipeline evaluates whether to run readiness and finishing
- **THEN** readiness and finishing SHALL be allowed to run
- **AND** deterministic validation/readiness/publishability gates SHALL remain authoritative.

#### Scenario: Missing accepted reconciliation remains blocked

- **GIVEN** ModuleBuilder generation succeeded
- **AND** final blocker classification found editorial blockers
- **AND** no accepted final reconciliation report exists
- **WHEN** final publication status is composed
- **THEN** playable publication SHALL remain blocked
- **AND** the GUI SHALL identify final reconciliation as the next required action.
