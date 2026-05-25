## Purpose

Define the structured report format for the backstage auditor: grouped findings, evidence references, report consistency summary, and next-step recommendation.

## Requirements

### Requirement: Auditor SHALL emit grouped findings and recommendations

The accurate-ingest backstage auditor SHALL produce a structured report that groups findings by deterministic audit domain and recommends the next action.

Finding domains SHALL include:

- `source_fidelity`
- `build_fidelity`
- `validation`
- `readiness`
- `semantic_publishability`
- `report_consistency`
- `artifact_presence`

#### Scenario: Report disagreement is explicit

- **GIVEN** source-fidelity reports indicate `pass`
- **AND** toolkit or publishability reports indicate `fail`, `blocked`, or stale blocker state
- **WHEN** the auditor runs
- **THEN** the audit report SHALL include a `report_consistency` finding describing the disagreement
- **AND** the recommendation SHALL identify a next diagnostic or refresh step rather than silently choosing one report as truth.

#### Scenario: Findings cite evidence

- **GIVEN** the auditor emits a finding
- **WHEN** the finding is inspected
- **THEN** it SHALL cite one or more evidence references
- **AND** each evidence reference SHALL resolve to a collected evidence item.

#### Scenario: Next-step recommendation is compact

- **GIVEN** an audit completes
- **WHEN** `recommendation.json` is inspected
- **THEN** it SHALL include a recommended action
- **AND** it SHALL include the reason and supporting evidence references
- **AND** it SHALL identify whether repair, report refresh, OpenSpec work, or no action is recommended.

### Requirement: Auditor SHALL preserve deterministic gate authority

The audit report SHALL summarize deterministic gate outputs but SHALL NOT replace or override benchmark, validation, readiness, or publishability gates.

#### Scenario: Blocking publishability remains blocking

- **GIVEN** publishability output contains blocking errors
- **WHEN** the auditor summarizes the module
- **THEN** it SHALL report those errors as findings
- **AND** it SHALL NOT mark the module publishable unless the authoritative publishability output does so.
