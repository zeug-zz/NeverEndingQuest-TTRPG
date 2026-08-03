# accurate-ingest-final-reconciliation-reporting Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-llm-builder-final-editor. Update Purpose after archive.
## Requirements
### Requirement: Final reconciliation report SHALL record accepted, blocked, and failed outcomes honestly

The final editor SHALL persist `final_reconciliation_report.json` after final reconciliation attempts and SHALL include decisions, changed files, validation outcome, publication outcome, and source-fidelity effective status.

#### Scenario: Accepted reconciliation report is persisted

- **GIVEN** final reconciliation succeeds
- **AND** deterministic validation and publication gates pass
- **WHEN** final reporting runs
- **THEN** `final_reconciliation_report.json` SHALL record `reconciliation_status=accepted`
- **AND** it SHALL record `source_fidelity_effective_status=reconciled_degraded` when original source fidelity was blocked or degraded
- **AND** it SHALL preserve original source-fidelity diagnostics.

#### Scenario: Blocked reconciliation report is persisted

- **GIVEN** final reconciliation cannot apply a valid patch or deterministic gates fail
- **WHEN** final reporting runs
- **THEN** `final_reconciliation_report.json` SHALL record a blocked or failed status
- **AND** playable publication SHALL remain blocked.

#### Scenario: Build report consumes accepted final reconciliation

- **GIVEN** an accepted final reconciliation report exists
- **AND** validation, readiness, publishability, and report agreement pass
- **WHEN** toolkit build reporting runs
- **THEN** reports SHALL distinguish playable publication status from source-fidelity status
- **AND** GUI/report output SHALL NOT imply clean source fidelity unless source fidelity truly passed.

