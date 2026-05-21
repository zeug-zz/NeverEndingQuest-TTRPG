## ADDED Requirements

### Requirement: Clean accurate-ingest diagnostics SHALL NOT create mandatory pre-build approval

Clean accurate-ingest builds SHALL be able to proceed without pausing for user approval solely because source-fidelity diagnostics or review payloads exist.

#### Scenario: Clean diagnostics proceed to build

- **GIVEN** an accurate-ingest GUI job has no source-fidelity blockers requiring operator decision
- **WHEN** source diagnostics are available
- **THEN** the job SHALL continue toward build without entering a mandatory `awaiting_review` state
- **AND** the diagnostics MAY remain visible through an optional review/diagnostics panel.

#### Scenario: Required review still blocks when backend requires it

- **GIVEN** the backend marks a job as requiring review because of blockers, stale review state, non-approvable fidelity, or explicit waiver need
- **WHEN** the GUI receives the required-review state
- **THEN** required review controls SHALL remain visible
- **AND** the job SHALL NOT silently continue past the required decision.

### Requirement: GUI copy SHALL distinguish diagnostics from approval gates

The Module Toolkit UI SHALL avoid presenting optional source-fidelity diagnostics as a mandatory approval gate for clean builds.

#### Scenario: Optional diagnostics shown

- **GIVEN** a clean accurate-ingest job has diagnostics available
- **WHEN** the GUI renders status or review copy
- **THEN** the copy SHALL frame the panel as diagnostics, warnings, blockers, or waiver/debugging context
- **AND** it SHALL NOT imply the operator must approve before a clean build can proceed.
