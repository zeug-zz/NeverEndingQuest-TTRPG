## Purpose

Define how the backstage auditor collects deterministic accurate-ingest evidence from existing module report files without mutating module artifacts.

## Requirements

### Requirement: Auditor SHALL collect deterministic accurate-ingest evidence

The accurate-ingest backstage auditor SHALL collect existing deterministic evidence for a requested module without mutating module artifacts.

Evidence inputs SHALL include existing files when present:

- `accurate_ingest_benchmark_report.json`
- `toolkit_build_report.json`
- `validation_report.json`
- `source_fidelity_report.json`
- `build_fidelity_report.json`
- publishability audit JSON produced by an existing read-only command or captured fixture

#### Scenario: Existing report files become evidence references

- **GIVEN** a module directory containing accurate-ingest reports
- **WHEN** the auditor runs for that module
- **THEN** the auditor SHALL record each report as an evidence item
- **AND** each file evidence item SHALL include path, existence status, parse status, and compact status summary
- **AND** file evidence SHOULD include a content hash where practical.

#### Scenario: Missing optional report is a finding, not a crash

- **GIVEN** a module directory missing an optional accurate-ingest report
- **WHEN** the auditor runs
- **THEN** the auditor SHALL continue
- **AND** it SHALL emit an `artifact_presence` warning or finding for the missing report.

#### Scenario: Missing module fails clearly

- **GIVEN** a requested module slug that does not resolve to a module directory
- **WHEN** the auditor runs
- **THEN** the auditor SHALL fail with a clear missing-module error
- **AND** it SHALL NOT create or repair the module directory.

### Requirement: Auditor SHALL use compact evidence summaries

The auditor SHALL NOT copy large source bodies or full report bodies into its final report artifacts.

#### Scenario: Large report is summarized by reference

- **GIVEN** a large report file
- **WHEN** the auditor records evidence
- **THEN** the audit output SHALL store the report path and compact summary
- **AND** it SHALL NOT embed the full raw report body.
