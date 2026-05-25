# accurate-ingest-builder-audit-next-step-routing Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-builder-audit-briefing. Update Purpose after archive.
## Requirements
### Requirement: Brief Generator SHALL classify deterministic builder lanes

The brief generator SHALL classify the next builder lane from audit recommendation and finding state without authorizing mutation.

Allowed lanes SHALL be:

- `diagnose_reports`
- `repair_artifacts`
- `openspec_work`
- `review_warnings`
- `no_action`

#### Scenario: Report disagreement maps to diagnosis

- **GIVEN** an audit recommendation of `investigate_disagreement`
- **WHEN** the brief generator classifies the lane
- **THEN** the builder lane SHALL be `diagnose_reports`.

#### Scenario: Artifact repair maps to repair lane

- **GIVEN** an audit recommendation of `repair_artifacts`
- **WHEN** the brief generator classifies the lane
- **THEN** the builder lane SHALL be `repair_artifacts`.

#### Scenario: OpenSpec work maps to OpenSpec lane

- **GIVEN** an audit recommendation of `openspec_work`
- **WHEN** the brief generator classifies the lane
- **THEN** the builder lane SHALL be `openspec_work`.

#### Scenario: Warnings map to review lane

- **GIVEN** an audit recommendation of `review_warnings`
- **WHEN** the brief generator classifies the lane
- **THEN** the builder lane SHALL be `review_warnings`.

#### Scenario: No action stays no action

- **GIVEN** an audit recommendation of `no_action`
- **WHEN** the brief generator classifies the lane
- **THEN** the builder lane SHALL be `no_action`.

### Requirement: Brief Generator SHALL expose lane rationale

The builder brief SHALL explain why a lane was chosen.

#### Scenario: Lane rationale is present

- **GIVEN** a builder lane is classified
- **WHEN** the brief is inspected
- **THEN** it SHALL include a short rationale and supporting evidence references.

