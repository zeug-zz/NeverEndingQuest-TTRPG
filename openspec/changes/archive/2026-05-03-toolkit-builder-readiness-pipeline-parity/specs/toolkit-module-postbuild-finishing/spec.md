## MODIFIED Requirements

### Requirement: Toolkit builds run a shared post-build finishing pass
Toolkit-generated module directories MUST run a shared post-build readiness and finishing sequence after raw generation succeeds so they do not bypass the quality stages already used by the ingest workflow.

#### Scenario: Successful raw build enters readiness before finishing
- **WHEN** `ModuleBuilder.build_module(...)` completes successfully for a toolkit build
- **THEN** the toolkit MUST run readiness convergence before declaring the build fully complete
- **AND** the toolkit MUST run the shared post-build finishing pass only after readiness reports `ready_for_finishing`.

#### Scenario: Finishing pass reuses existing quality stages
- **WHEN** the toolkit runs its post-build finishing pass
- **THEN** the pass MUST include continuity normalization, semantic authority enrichment, registry verification, monster materialization, and publication evaluation or their shared wrappers
- **AND** MUST NOT require a duplicate reimplementation of those stages inside the toolkit transport layer.

#### Scenario: Monster materialization stage reports direct helper outcome
- **WHEN** the finishing pass executes monster materialization
- **THEN** the stage result MUST come from direct helper execution outcome
- **AND** MUST NOT depend on parsing subprocess stderr/stdout to infer success or failure.

## ADDED Requirements

### Requirement: Legacy builder finishing SHALL be gated by readiness
The legacy Describe your Adventure builder path SHALL not call the shared finisher directly after raw generation unless readiness convergence has passed.

#### Scenario: Direct finisher bypass is rejected by contract
- **WHEN** the legacy builder implementation is inspected or tested
- **THEN** there SHALL be an explicit readiness call between raw `build_module(...)` success and `run_toolkit_module_postbuild_finishing(...)` or `refresh_toolkit_build_report(...)`
- **AND** final finishing SHALL be conditional on `ready_for_finishing`.

#### Scenario: Existing uploader behavior remains gated
- **WHEN** the uploader packet build path completes raw builder execution
- **THEN** it SHALL still enforce readiness before finishing
- **AND** this change SHALL NOT remove the existing uploader readiness gate.
