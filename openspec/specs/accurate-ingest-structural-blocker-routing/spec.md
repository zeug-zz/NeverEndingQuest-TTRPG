# accurate-ingest-structural-blocker-routing Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-modulebuilder-structural-repair. Update Purpose after archive.
## Requirements
### Requirement: Structural Validation Failures Block Final Editor Invocation

Accurate-ingest builds SHALL route structural validation failures as fatal blockers before any final-editor LLM invocation.

#### Scenario: Reference integrity failure is fatal
- **GIVEN** full-module validation reports a reference-integrity failure after structural repair
- **WHEN** packet-builder routing evaluates final reconciliation eligibility
- **THEN** final-editor invocation SHALL be skipped
- **AND** the build result SHALL be blocked with structural diagnostics.

#### Scenario: Spatial contract failure is fatal
- **GIVEN** full-module validation reports a spatial contract failure after structural repair
- **WHEN** packet-builder routing evaluates final reconciliation eligibility
- **THEN** final-editor invocation SHALL be skipped
- **AND** the build result SHALL not report `final_reconciliation_required` or `final_reconciliation_accepted` as the active path.

#### Scenario: Party schema failure is fatal
- **GIVEN** full-module validation reports a party tracker schema or calendar failure after structural repair
- **WHEN** packet-builder routing evaluates final reconciliation eligibility
- **THEN** final-editor invocation SHALL be skipped
- **AND** the build result SHALL preserve the party validation diagnostic.

### Requirement: Accepted Reconciliation Report Cannot Override Structural Failure

An accepted `final_reconciliation_report.json` SHALL NOT make a structurally invalid module playable.

#### Scenario: Accepted report exists but validation is fatal
- **GIVEN** a module workspace contains an accepted final reconciliation report from an earlier run
- **AND** current full-module validation reports fatal structural failures
- **WHEN** the accurate-ingest build result is composed
- **THEN** the accepted report SHALL be ignored for playable publication routing
- **AND** the build SHALL remain blocked until structural validation passes.

### Requirement: Editorial Blockers Still Use Final Reconciliation

Editorial-only source-fidelity blockers SHALL continue to use the existing final reconciliation path after structural validation passes.

#### Scenario: Structural validation passes and editorial blockers remain
- **GIVEN** full-module validation passes after structural repair
- **AND** blocker classification contains only editorial source-fidelity blockers
- **WHEN** packet-builder routing evaluates final reconciliation eligibility
- **THEN** final-editor reconciliation SHALL remain eligible under the existing final-editor contract.

