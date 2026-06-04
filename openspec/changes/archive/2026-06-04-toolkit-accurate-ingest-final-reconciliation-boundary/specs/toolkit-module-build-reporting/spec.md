## ADDED Requirements

### Requirement: Toolkit build reporting SHALL include final reconciliation status

Toolkit build reporting SHALL surface final reconciliation status and source-fidelity effective status when an accurate-ingest build has editorial/source-fidelity blockers.

#### Scenario: Final reconciliation required is reported

- **GIVEN** an accurate-ingest build has editorial blockers and no accepted final reconciliation report
- **WHEN** the toolkit writes or emits build status
- **THEN** the report SHALL include `final_reconciliation_required: true`
- **AND** it SHALL include the path to `final_reconciliation_brief.json` when available.

#### Scenario: Accepted reconciliation is reported

- **GIVEN** an accurate-ingest build has accepted final reconciliation
- **WHEN** the toolkit writes `toolkit_build_report.json`
- **THEN** the report SHALL include final reconciliation status
- **AND** it SHALL include `source_fidelity_effective_status` distinct from the original source-fidelity status.

## MODIFIED Requirements

### Requirement: Toolkit build reporting distinguishes generation from finishing

Toolkit build reporting MUST distinguish raw module generation success from post-build finishing outcomes and final reconciliation outcomes.

#### Scenario: Finishing failure is reported after successful generation

- **WHEN** raw module generation succeeds but a required finishing stage fails
- **THEN** the toolkit MUST report that generation succeeded but finishing failed
- **AND** MUST expose enough detail for the operator to identify the failed finishing stage.

#### Scenario: Degraded finishing is reported explicitly

- **WHEN** the finishing pass completes with degraded-but-usable results
- **THEN** the toolkit MUST report a degraded outcome rather than a plain success message
- **AND** MUST preserve the generated module identity in the result payload.

#### Scenario: Final reconciliation distinguishes playable from source-faithful

- **WHEN** final reconciliation accepts source-fidelity blockers and final publication gates pass
- **THEN** the toolkit MUST report playable publication separately from clean source-fidelity status
- **AND** MUST NOT report clean source-fidelity pass unless source fidelity actually passed.

### Requirement: Toolkit builds persist a post-build report

Toolkit builds MUST persist a machine-readable post-build report or sidecar so parity-stage outcomes can be reviewed outside transient socket messages.

#### Scenario: Post-build report is written

- **WHEN** a toolkit build finishes its post-build parity pass
- **THEN** the system MUST write a machine-readable report tied to the generated module
- **AND** the report MUST include the final top-level status and finishing-stage details.

#### Scenario: MMG completion refreshes persisted report after media debt remediation

- **GIVEN** a module whose persisted toolkit build report still indicates media debt or `Needs Module Media Generator`
- **AND** the module's MMG workflow successfully completes required media generation for that module
- **WHEN** the MMG completion path finalizes successfully
- **THEN** the system SHALL invoke the shared persisted report refresh contract for that module
- **AND** the rewritten `toolkit_build_report.json` SHALL reflect the latest publishability-facing blocker state instead of the stale pre-MMG state.

#### Scenario: MMG report refresh fails open

- **GIVEN** a successful MMG media-generation run for a module
- **AND** the subsequent persisted report refresh path degrades or fails
- **WHEN** the system finalizes the MMG completion flow
- **THEN** the MMG completion result SHALL still report media-generation success to the operator
- **AND** sidebar consumers SHALL remain on the previous persisted report until a later valid refresh path runs
- **AND** the system SHALL NOT substitute live MMG table status for persisted sidebar status.
