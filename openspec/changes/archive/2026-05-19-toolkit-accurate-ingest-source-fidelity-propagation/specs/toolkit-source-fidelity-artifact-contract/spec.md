## ADDED Requirements

### Requirement: Accurate-ingest builds SHALL persist final source-fidelity report

Accurate-ingest module builds SHALL persist the final source-fidelity status into a module-level `source_fidelity_report.json` artifact.

#### Scenario: Module-level source-fidelity report created

- **GIVEN** an accurate-ingest GUI build completes source-fidelity evaluation
- **WHEN** the module artifact set is written
- **THEN** `modules/<slug>/source_fidelity_report.json` SHALL exist
- **AND** it SHALL include `report_version: "source_fidelity_report.v1"`
- **AND** it SHALL include `source_fidelity_status` as one of `pass`, `degraded`, `blocked`, or `unknown`
- **AND** it SHALL include category detail as an array or equivalent structured field.

#### Scenario: Source-fidelity provenance preserved

- **GIVEN** source hash, source path, workspace artifacts, benchmark detail, build-fidelity detail, or waiver data are available
- **WHEN** `source_fidelity_report.json` is written
- **THEN** the report SHALL preserve available provenance fields without requiring all optional fields to exist.

### Requirement: Source-fidelity report SHALL be compact and additive

The module-level source-fidelity report SHALL use a compact v1 contract and SHALL NOT remove or rename existing benchmark report fields.

#### Scenario: Benchmark report compatibility preserved

- **GIVEN** a module already has `accurate_ingest_benchmark_report.json`
- **WHEN** `source_fidelity_report.json` is added
- **THEN** the benchmark report MAY remain in place
- **AND** consumers SHALL treat `source_fidelity_report.json` as final status, not as a replacement for benchmark detail.
