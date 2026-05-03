# toolkit-builder-readiness-pipeline-parity Specification

## Purpose
TBD - created by archiving change toolkit-builder-readiness-pipeline-parity. Update Purpose after archive.
## Requirements
### Requirement: Legacy builder SHALL run readiness convergence before finishing
The Module Toolkit's Describe your Adventure builder path SHALL run the shared toolkit readiness convergence gate after raw module generation succeeds and before invoking the shared toolkit post-build finisher.

#### Scenario: Successful raw legacy build enters readiness convergence
- **WHEN** the legacy builder socket path completes `ModuleBuilder.build_module(...)` successfully
- **THEN** it SHALL invoke the shared toolkit readiness convergence gate for the generated module slug
- **AND** it SHALL not invoke final toolkit finishing until readiness reports `ready_for_finishing`.

#### Scenario: Readiness failure blocks finishing
- **WHEN** raw legacy builder generation succeeds
- **AND** readiness convergence returns any status other than `ready_for_finishing`
- **THEN** the legacy builder path SHALL stop before final toolkit finishing
- **AND** it SHALL surface a readiness failure payload to the UI.

#### Scenario: Uploader-specific front-half stages remain uploader-only
- **WHEN** a user submits the legacy Describe your Adventure form
- **THEN** the system SHALL not require Homebrew source preflight, normalization, review packet generation, source-rights classification, or watcher sidecar artifacts
- **AND** it SHALL treat the generated module as a toolkit-source module for readiness and publishability purposes.

### Requirement: Shared readiness adapter SHALL avoid duplicate convergence implementations
The implementation SHALL provide one shared readiness convergence entrypoint or factored core used by both uploader packet builds and legacy builder builds.

#### Scenario: Uploader and legacy builder use same convergence implementation
- **WHEN** uploader packet builds and legacy builder narrative builds reach post-builder validation
- **THEN** both paths SHALL use the same readiness validation, deterministic repair, semantic repair, and structural audit behavior
- **AND** neither path SHALL maintain a separate duplicate repair loop.

#### Scenario: Host file remains a thin hook
- **WHEN** the legacy builder socket handler calls readiness convergence
- **THEN** reusable readiness orchestration SHALL live in extension/helper code outside `web/web_interface.py`
- **AND** any required host hook edits SHALL be marked with `# TABLETOP MODE:`.

### Requirement: Legacy builder SHALL persist auditable readiness output
Legacy builder readiness runs SHALL persist or return machine-readable readiness artifacts sufficient to audit validation, repair, convergence, and failure outcomes.

#### Scenario: Readiness artifacts include convergence fields
- **WHEN** a legacy builder readiness run completes
- **THEN** its result SHALL include `validation`, `readiness_audit`, `repair_attempts`, `deterministic_passes`, `semantic_passes`, `convergence_outcome`, `fixed_point_detected`, `residual_blocker_classes`, and `ready_for_finishing` or equivalent fields
- **AND** the UI SHALL be able to include those details in failure output without rerunning live audits.

#### Scenario: Raw generation success but readiness system unavailable
- **WHEN** raw legacy builder generation succeeds
- **AND** the readiness adapter cannot be imported or cannot run
- **THEN** the build SHALL fail closed with an explicit readiness-system failure
- **AND** it SHALL not be reported as a completed module build.

### Requirement: Legacy builder UI SHALL distinguish pipeline phases
The legacy builder UI and socket payloads SHALL distinguish raw generation, readiness convergence, final finishing, publishability, and media handoff outcomes.

#### Scenario: Readiness phase progress is visible
- **WHEN** the legacy builder starts readiness convergence
- **THEN** it SHALL emit progress or status data identifying readiness validation, readiness repair, or readiness audit activity
- **AND** the user SHALL not see readiness work mislabeled as raw generation.

#### Scenario: Final status identifies outcome class
- **WHEN** a legacy builder run ends
- **THEN** the final payload SHALL distinguish raw-generation failure, readiness failure, finishing failure, non-publishable result, publishable success, and success with media handoff.

#### Scenario: Stale semantic-probe note removed
- **WHEN** the legacy builder reports final post-build status
- **THEN** it SHALL not state that semantic publication probes are absent if the shared finisher has run publishability evaluation with semantic audit/probe gates.

