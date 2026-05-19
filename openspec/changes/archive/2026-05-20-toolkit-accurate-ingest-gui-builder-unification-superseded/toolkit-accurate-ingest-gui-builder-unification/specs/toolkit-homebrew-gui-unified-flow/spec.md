## ADDED Requirements

### Requirement: GUI accurate-ingest SHALL expose one unified build workflow

The Module Builder GUI SHALL present uploaded readable adventures as one user workflow even when implementation uses deterministic extraction, multi-pass normalization, blueprint generation, seed writing, enrichment, and finisher stages internally.

#### Scenario: Accurate-ingest job pauses for fidelity review

- **GIVEN** an uploaded source produces accurate-ingest source/fidelity/blueprint artifacts
- **WHEN** normalization and blueprint generation complete
- **THEN** the job SHALL enter `awaiting_review`
- **AND** it SHALL NOT seed or build module files until the review is approved.

#### Scenario: Approved job proceeds through seed and enrichment states

- **GIVEN** a job has approved fidelity review
- **AND** blueprint-native GUI build is enabled
- **WHEN** build starts
- **THEN** the job SHALL expose `seeding_module`, `enriching_module`, `build_fidelity`, `readiness`, `finishing`, and `publishability_audit` stages as applicable.

### Requirement: GUI accurate-ingest SHALL preserve legacy behavior when disabled

When blueprint-native GUI build is disabled or a workspace has no accurate-ingest artifacts, existing packet builder and legacy Module Builder behavior SHALL remain unchanged.

#### Scenario: Feature flag disabled

- **GIVEN** `ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD` is false
- **WHEN** an approved packet build starts
- **THEN** the current packet builder path SHALL run as before
- **AND** no seed writer SHALL be invoked.

#### Scenario: Legacy Describe-your-Adventure build

- **GIVEN** a user starts a concept-first Module Builder build without source graph or blueprint artifacts
- **WHEN** the build starts
- **THEN** the legacy `ModuleBuilder` path SHALL remain available
- **AND** accurate-ingest fidelity review SHALL NOT be required.

### Requirement: GUI status responses SHALL surface source-truth progress

GUI job review/status responses SHALL include compact source structure, blueprint, seed, enrichment, build-fidelity, and final report metadata when available.

#### Scenario: Review payload includes blueprint coverage

- **GIVEN** a job is awaiting review
- **WHEN** the GUI requests review data
- **THEN** the response SHALL include source counts, fidelity blockers/warnings, blueprint status, and blueprint coverage counts.

#### Scenario: Final payload includes artifact links

- **GIVEN** a unified accurate-ingest build completes
- **WHEN** the GUI requests final job status
- **THEN** the response SHALL include paths or availability indicators for `toolkit_build_report.json`, `source_fidelity_report.json`, `build_fidelity_report.json`, and `MODULE_SUMMARY.md`.
