## ADDED Requirements

### Requirement: Fidelity review UI SHALL be visible for required review states

The toolkit SHALL load and render the review panel for required review states even when optional homebrew advanced mode is disabled.

#### Scenario: Awaiting review with advanced mode disabled

- **GIVEN** a homebrew ingest job has `job.status == "awaiting_review"`
- **AND** `HOME_BREW_ADVANCED_MODE` is false
- **WHEN** the upload polling handler detects the awaiting-review state
- **THEN** the toolkit SHALL call review loading in required mode
- **AND** the review loading function SHALL NOT return early because advanced mode is disabled
- **AND** the operator SHALL see review controls instead of only raw JSON output.

#### Scenario: Optional review loading remains hidden when not required

- **GIVEN** no job is in a required review state
- **AND** `HOME_BREW_ADVANCED_MODE` is false
- **WHEN** optional review loading is requested
- **THEN** existing advanced-panel hiding behavior SHALL be preserved.

### Requirement: Awaiting-review UI SHALL always expose an action surface

The toolkit SHALL render an action surface for `awaiting_review` jobs regardless of whether the fidelity payload is fully approvable.

#### Scenario: Approvable accurate-ingest review

- **GIVEN** an accurate-ingest job is awaiting review
- **AND** the fidelity review payload has `can_approve == true`
- **WHEN** the review panel renders
- **THEN** the UI SHALL show an enabled `Approve Fidelity Review` control
- **AND** the UI SHALL show a `Reject Review` control
- **AND** the UI SHALL show a `Refresh Review` control.

#### Scenario: Non-approvable accurate-ingest review

- **GIVEN** an accurate-ingest job is awaiting review
- **AND** the fidelity review payload has `can_approve != true`
- **WHEN** the review panel renders
- **THEN** the UI SHALL show a disabled approve control
- **AND** the UI SHALL show an explanation for why approval is disabled
- **AND** the UI SHALL show `Reject Review` and `Refresh Review` controls.

#### Scenario: Missing fidelity payload in awaiting-review state

- **GIVEN** a job is awaiting review
- **AND** the review endpoint does not provide a usable `fidelity_review` payload
- **WHEN** the review UI renders
- **THEN** the UI SHALL show a disabled approve state that explains review details are unavailable
- **AND** the UI SHALL show a refresh control
- **AND** the UI SHALL NOT leave the operator with only raw JSON output.

### Requirement: Approved review state SHALL expose build continuation

The toolkit SHALL expose a build continuation control after an accurate-ingest review has been approved.

#### Scenario: Approved accurate-ingest review waits for explicit build start

- **GIVEN** an accurate-ingest job has `job.status == "approved_for_build"`
- **WHEN** the review UI renders
- **THEN** the UI SHALL show a `Start Build` control
- **AND** the build SHALL not auto-start unless existing accurate-ingest behavior explicitly requires it.
