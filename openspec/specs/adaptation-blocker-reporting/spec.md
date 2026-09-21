# adaptation-blocker-reporting Specification

## Purpose
Ensure adaptation monster guardrail and closure failures produce current, bounded, actionable job reports instead of generic unknown failure classifications or stale artifact references.

## Requirements

### Requirement: Early Adaptation Blockers Are Classified

Every adaptation blocker returned before normal readiness or finishing stages SHALL include a bounded failure classification with a concrete failure code and failed stage.

#### Scenario: Semantic monster reference blocks build

- **WHEN** an adaptation monster entry cannot be canonicalized or resolved
- **THEN** the job result SHALL identify the semantic monster guardrail stage
- **AND** the failure code SHALL identify unresolved or ambiguous monster reference handling
- **AND** the report SHALL include bounded source-location diagnostics

#### Scenario: Closure or materialization blocks build

- **WHEN** staging monster closure or artifact verification fails
- **THEN** the job result SHALL identify the closure/materialization stage
- **AND** the concrete error SHALL be persisted before the job becomes terminal

#### Scenario: Canonical stat generation blocks materialization

- **WHEN** an approved canonical monster cannot be reused and bounded LLM generation fails or returns an invalid artifact
- **THEN** the job result SHALL identify the canonical generation stage
- **AND** the failure code SHALL distinguish timeout, provider failure, invalid JSON, incomplete schema, or staging-safety failure when known
- **AND** the report SHALL include the bounded canonical reference without exposing raw provider payloads

### Requirement: Adaptation Status Uses Current Build Result

The adaptation job status projection SHALL use the current blocked build result and SHALL NOT present stale `build_result.json` or finishing artifacts as the current attempt's result.

#### Scenario: Early failure has no readiness report

- **WHEN** a build fails before readiness writes its normal report artifacts
- **THEN** the job SHALL persist a current build result or explicit failure artifact
- **AND** retry/finishing routes SHALL not treat stale artifacts from an earlier attempt as current

#### Scenario: GUI renders blocked adaptation

- **WHEN** the adaptation job reaches a terminal blocked state
- **THEN** the GUI SHALL display the concrete bounded failure code or stage
- **AND** raw provider payloads SHALL remain excluded
