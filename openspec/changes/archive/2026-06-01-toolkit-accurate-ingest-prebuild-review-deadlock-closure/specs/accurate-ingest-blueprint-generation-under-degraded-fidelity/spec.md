## ADDED Requirements

### Requirement: Degraded Pre-Build Fidelity Diagnostics SHALL NOT Block Blueprint Generation

Accurate-ingest jobs MUST generate a bounded builder blueprint when normalized source, packet data, and source text are readable, even if pre-build fidelity diagnostics are degraded.

#### Scenario: Degraded diagnostics still produce blueprint

- **GIVEN** an accurate-ingest job has readable source text and normalized packet artifacts
- **AND** pre-build source-fidelity diagnostics contain degraded or warning findings
- **WHEN** the blueprint generation stage runs
- **THEN** the job SHALL attempt to write `builder_blueprint.json`
- **AND** degraded diagnostics SHALL be carried as report metadata or warnings
- **AND** the job SHALL NOT enter mandatory `awaiting_review` solely because those degraded diagnostics exist.

#### Scenario: Missing prerequisites fail explicitly

- **GIVEN** an accurate-ingest job lacks readable source text, normalized packet data, or other required blueprint prerequisites
- **WHEN** the blueprint generation stage runs
- **THEN** the job SHALL fail with an explicit missing or malformed artifact diagnostic
- **AND** the GUI SHALL NOT present the job as successfully built.

### Requirement: Final Gates SHALL Remain Authoritative

Pre-build continuation MUST NOT weaken final validation, benchmark, publishability, playable-publication, or report-agreement gates.

#### Scenario: Built module remains blocked by final gates

- **GIVEN** degraded pre-build diagnostics continue to ModuleBuilder
- **AND** the resulting module fails schema validation, source-fidelity benchmark, publishability, playable-publication, or report-agreement checks
- **WHEN** final status is computed
- **THEN** the build SHALL be reported as blocked or not playable
- **AND** final status SHALL include the blocker class and recommended next action.

### Requirement: Explicit Required Review SHALL Remain Strict

Jobs that explicitly enter required fidelity review MUST keep existing backend approval protections.

#### Scenario: Explicit required review blocks continuation

- **GIVEN** the backend marks a job as requiring fidelity review with a current non-approvable or stale-signature review payload
- **WHEN** the operator attempts to continue or approve the job
- **THEN** the backend SHALL preserve the existing strict rejection behavior
- **AND** the job SHALL NOT continue through a broad force-approval path.
