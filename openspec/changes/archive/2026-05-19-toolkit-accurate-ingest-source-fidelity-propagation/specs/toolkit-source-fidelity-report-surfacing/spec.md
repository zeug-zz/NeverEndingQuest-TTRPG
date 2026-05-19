## ADDED Requirements

### Requirement: Toolkit build report SHALL mirror final source-fidelity status

`toolkit_build_report.json` SHALL surface the same effective source-fidelity status used by the final publishability audit.

#### Scenario: Build report includes source-fidelity fields

- **GIVEN** an accurate-ingest build has final source-fidelity status
- **WHEN** `toolkit_build_report.json` is written
- **THEN** it SHALL include `source_fidelity_status`
- **AND** it SHALL include category details or an equivalent source-fidelity summary
- **AND** it SHALL reference `source_fidelity_report.json` when that artifact exists.

#### Scenario: Build report and CLI audit agree

- **GIVEN** a module has `source_fidelity_report.json`
- **WHEN** the toolkit build report is inspected
- **AND** `scripts/audit_module_publishability.py` audits the module
- **THEN** both surfaces SHALL report the same effective `source_fidelity_status`.

### Requirement: Derived summary artifacts SHALL NOT repair source fidelity

Derived prose artifacts such as `MODULE_SUMMARY.md` SHALL NOT be treated as source-fidelity evidence or a repair path for blocked source fidelity.

#### Scenario: Module summary cannot override source fidelity

- **GIVEN** `source_fidelity_report.json` has `source_fidelity_status: "blocked"`
- **AND** `MODULE_SUMMARY.md` exists
- **WHEN** final reports and publishability are composed
- **THEN** `MODULE_SUMMARY.md` SHALL NOT change the effective source-fidelity status
- **AND** publication SHALL remain blocked by source fidelity.
