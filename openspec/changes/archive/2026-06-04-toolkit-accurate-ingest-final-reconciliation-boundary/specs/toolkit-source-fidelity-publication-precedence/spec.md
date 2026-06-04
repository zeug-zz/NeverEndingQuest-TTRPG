## MODIFIED Requirements

### Requirement: Publishability audit SHALL prefer final module-level source-fidelity report

The publishability audit SHALL load source-fidelity status using deterministic precedence: `source_fidelity_report.json`, then `accurate_ingest_benchmark_report.json`, then legacy `unknown`. After source-fidelity status lookup, the audit SHALL also consume accepted final reconciliation status when present.

#### Scenario: Module-level report wins over stale benchmark

- **GIVEN** a module has `source_fidelity_report.json` with `source_fidelity_status: "blocked"`
- **AND** it has `accurate_ingest_benchmark_report.json` with `source_fidelity_status: "pass"`
- **WHEN** `scripts/audit_module_publishability.py` audits the module
- **THEN** the effective `source_fidelity_status` SHALL be `blocked`.

#### Scenario: Benchmark fallback preserved

- **GIVEN** a module has no `source_fidelity_report.json`
- **AND** it has `accurate_ingest_benchmark_report.json` with `source_fidelity_status: "pass"`
- **WHEN** publishability audit runs
- **THEN** the audit SHALL use the benchmark source-fidelity status.

#### Scenario: Legacy unknown remains fail-open

- **GIVEN** a module has no source-fidelity artifact
- **WHEN** publishability audit runs
- **THEN** `source_fidelity_status` SHALL be `unknown`
- **AND** source-fidelity absence alone SHALL NOT block publishability.

#### Scenario: Final reconciliation status is consumed after source status lookup

- **GIVEN** a module or workspace has final reconciliation status `accepted`
- **AND** source_fidelity_status is `blocked`
- **WHEN** publishability audit composes final status
- **THEN** the audit SHALL preserve `source_fidelity_status=blocked`
- **AND** it SHALL expose an effective reconciled source-fidelity status for publication composition.

### Requirement: Blocked source fidelity SHALL block final publishability unless reconciliation is accepted

The final publishability gate SHALL block publication when effective source-fidelity status is `blocked` and no accepted final reconciliation status exists.

#### Scenario: Blocked source fidelity overrides passing readiness without reconciliation

- **GIVEN** readiness, semantic audit, and semantic probes pass
- **AND** effective `source_fidelity_status` is `blocked`
- **AND** no accepted final reconciliation status exists
- **WHEN** final publishability is composed
- **THEN** final `publishable_status` SHALL be `fail` or equivalent blocking status
- **AND** the report SHALL include a source-fidelity blocker.

#### Scenario: Blocked source fidelity is reconciled for playable publication

- **GIVEN** readiness, semantic audit, and semantic probes pass
- **AND** effective `source_fidelity_status` is `blocked`
- **AND** accepted final reconciliation provides `source_fidelity_effective_status=reconciled_degraded`
- **WHEN** final publishability is composed
- **THEN** source-fidelity SHALL NOT be the sole reason for `publishable_status=fail`
- **AND** the report SHALL include reconciled source-fidelity diagnostics.

#### Scenario: Degraded source fidelity follows waiver contract

- **GIVEN** effective `source_fidelity_status` is `degraded`
- **WHEN** final publishability is composed
- **THEN** degraded handling SHALL follow the existing waiver/composer contract
- **AND** this change SHALL NOT silently treat degraded as pass unless the existing waiver rules allow it.
