## Purpose

Define how the backstage auditor MAY invoke existing deterministic scripts in read-only JSON mode and capture their output as evidence without persisting refreshed artifacts.

## Requirements

### Requirement: Auditor MAY run existing scripts only in read-only JSON mode

The accurate-ingest backstage auditor MAY invoke existing deterministic scripts to collect current evidence, but it SHALL do so without writing refreshed module artifacts.

Allowed read-only command sources include:

- `scripts/benchmark_accurate_ingest.py --module <slug> --json`
- `scripts/audit_module_publishability.py --module <slug> --json`
- validation commands only when their invocation does not write back into module artifacts, or when tests use temp fixtures

#### Scenario: Benchmark command output is captured as evidence

- **GIVEN** benchmark collection is enabled
- **WHEN** the auditor runs the benchmark command in JSON mode
- **THEN** it SHALL capture exit code, parse status, and compact JSON summary as evidence
- **AND** it SHALL NOT persist the command output into `accurate_ingest_benchmark_report.json`.

#### Scenario: Publishability command output is captured as evidence

- **GIVEN** publishability collection is enabled
- **WHEN** the auditor runs publishability in JSON mode
- **THEN** it SHALL capture ready, publishable, and source-fidelity statuses as evidence
- **AND** it SHALL NOT persist refreshed publishability output into module artifacts.

#### Scenario: Command failure becomes a finding

- **GIVEN** an allowed read-only command fails
- **WHEN** the auditor completes
- **THEN** the command failure SHALL appear as a finding with evidence reference
- **AND** the auditor SHALL NOT silently downgrade the failure to pass.

### Requirement: Script parity SHALL not replace existing gate scripts

The auditor SHALL consume and summarize existing deterministic script outputs. It SHALL NOT replace benchmark, validation, readiness, or publishability scripts.

#### Scenario: Existing scripts remain authoritative

- **GIVEN** an auditor summary and an authoritative script output disagree
- **WHEN** the disagreement is detected
- **THEN** the auditor SHALL report the disagreement
- **AND** it SHALL not override the authoritative script status.
