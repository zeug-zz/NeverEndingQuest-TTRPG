# toolkit-homebrew-review-status-ux Specification

## Purpose
TBD - created by archiving change toolkit-fidelity-review-ui-deadlock. Update Purpose after archive.
## Requirements
### Requirement: Awaiting-review status copy SHALL identify fidelity review accurately

The toolkit SHALL not describe accurate-ingest fidelity review as a legacy review state.

#### Scenario: Accurate-ingest job pauses for fidelity review

- **GIVEN** an accurate-ingest job enters `awaiting_review`
- **WHEN** the upload status message is rendered
- **THEN** the status copy SHALL say the job is awaiting source-fidelity review
- **AND** it SHALL NOT use the misleading exact phrase `Legacy Homebrew job is awaiting review` for that state.

#### Scenario: Generic review state has unknown mode

- **GIVEN** a job enters `awaiting_review`
- **AND** the frontend cannot determine whether it is accurate-ingest or legacy review
- **WHEN** the upload status message is rendered
- **THEN** the status copy SHALL use a generic `Homebrew job is awaiting review` style message.

### Requirement: Raw JSON diagnostics SHALL be supplemental, not the only control surface

The toolkit MAY continue to render raw job/review JSON diagnostics, but diagnostics SHALL NOT be the only UI presented for a job that needs operator review.

#### Scenario: Awaiting-review raw JSON visible

- **GIVEN** the toolkit renders raw JSON for an awaiting-review job
- **WHEN** the status panel is displayed
- **THEN** the same screen SHALL also expose review controls or a refreshable review action surface.

