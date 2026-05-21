# toolkit-source-fidelity-report-surfacing Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-final-benchmark-publication-gate. Update Purpose after archive.
## Requirements
### Requirement: Source-fidelity status SHALL appear in publishability audit output

The publishability audit JSON output SHALL include a `source_fidelity_status` field with per-category breakdown when source graph artifacts are available.

#### Scenario: Module with source graph artifacts

- **GIVEN** a module has accurate-ingest source graph artifacts
- **WHEN** publishability audit runs
- **THEN** output SHALL include `source_fidelity_status` with value pass, degraded, or blocked
- **AND** output SHALL include per-category scores.

#### Scenario: Module without source graph artifacts

- **GIVEN** a module has no accurate-ingest source graph artifacts
- **WHEN** publishability audit runs
- **THEN** output SHALL include `source_fidelity_status: "unknown"`
- **AND** existing `ready_status` and `publishable_status` SHALL remain unchanged.

### Requirement: Toolkit finisher report SHALL surface source-fidelity status

The toolkit finisher report SHALL include source-fidelity status alongside existing readiness and publishability status fields.

#### Scenario: Module with source-fidelity pass

- **GIVEN** the benchmark runner returns pass for all categories
- **WHEN** the toolkit finisher generates the build report
- **THEN** the report SHALL include `source_fidelity_status: "pass"`
- **AND** existing `ready_status` and `publishable_status` SHALL remain present.

#### Scenario: Module with source-fidelity degraded

- **GIVEN** the benchmark runner returns degraded for one or more categories
- **WHEN** the toolkit finisher generates the build report
- **THEN** the report SHALL include `source_fidelity_status: "degraded"`
- **AND** degraded categories SHALL be listed.

### Requirement: Existing report fields SHALL NOT be removed or renamed

Integration of source-fidelity reporting SHALL be strictly additive to existing toolkit, publishability, and readiness report outputs. No existing field SHALL be removed, renamed, or have its semantics changed.

#### Scenario: Publishability audit run on module that previously passed all gates

- **GIVEN** a module previously returned ready_status=pass and publishable_status=pass
- **WHEN** publishability audit runs with source-fidelity integration active
- **THEN** ready_status SHALL still be pass
- **AND** publishable_status SHALL still be pass
- **AND** source_fidelity_status SHALL be added as an additional field.

### Requirement: Toolkit build report SHALL mirror final source-fidelity status

`toolkit_build_report.json` SHALL surface the same effective source-fidelity status used by the final publishability audit.

#### Scenario: Build report includes source-fidelity fields

- **GIVEN** an accurate-ingest build has final source-fidelity status
- **WHEN** `toolkit_build_report.json` is written
- **THEN** it SHALL include `source_fidelity_status`
- **AND** it SHALL include category details or an equivalent source-fidelity summary
- **AND** it SHALL reference `source_fidelity_report.json` when that artifact exists.

