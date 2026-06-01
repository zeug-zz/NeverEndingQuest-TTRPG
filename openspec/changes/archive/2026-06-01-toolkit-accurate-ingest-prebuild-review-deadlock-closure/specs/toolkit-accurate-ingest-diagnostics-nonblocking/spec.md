## MODIFIED Requirements

### Requirement: Clean accurate-ingest diagnostics SHALL NOT create mandatory pre-build approval

Clean or degraded accurate-ingest pre-build diagnostics SHALL NOT create mandatory pre-build approval unless the backend explicitly marks a current required-review state.

#### Scenario: Degraded diagnostics proceed to blueprint

- **GIVEN** an accurate-ingest GUI job has readable source and packet artifacts
- **AND** source-fidelity diagnostics include degraded findings, warnings, or non-terminal blockers from source atom classification
- **WHEN** blueprint generation is possible
- **THEN** the job SHALL continue toward blueprint/build artifact generation without entering mandatory `awaiting_review` solely because diagnostics exist
- **AND** diagnostics MAY remain visible through an optional review/diagnostics panel.

#### Scenario: Required review still blocks when backend requires it

- **GIVEN** the backend marks a job as requiring review because of explicit required-review state, stale review state, non-approvable fidelity, malformed source, missing artifact prerequisites, user rejection, or explicit waiver need
- **WHEN** the GUI receives the required-review state
- **THEN** required review controls SHALL remain visible
- **AND** the job SHALL NOT silently continue past the required decision.

### Requirement: GUI copy SHALL distinguish diagnostics from approval gates

The Module Toolkit UI SHALL avoid presenting optional or degraded source-fidelity diagnostics as a mandatory approval gate for builds that can still generate bounded artifacts.

#### Scenario: Optional diagnostics shown

- **GIVEN** an accurate-ingest job has diagnostics available
- **WHEN** the GUI renders status or review copy
- **THEN** the copy SHALL frame the panel as diagnostics, warnings, blockers, waiver context, or debugging context
- **AND** it SHALL NOT imply the operator must approve before bounded artifact generation can proceed unless the backend marks required review.
