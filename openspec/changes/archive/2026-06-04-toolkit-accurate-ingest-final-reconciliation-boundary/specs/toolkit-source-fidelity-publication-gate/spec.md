## MODIFIED Requirements

### Requirement: Publication gate SHALL compose independent status dimensions with reconciliation override

The publication gate SHALL compose `ready_status`, `publishable_status`, `source_fidelity_status`, and accepted final reconciliation status into a final publishable determination. Fatal readiness or publishability failures SHALL block publication. Blocked source fidelity SHALL block publication unless accepted final reconciliation supplies an effective reconciled source-fidelity status.

#### Scenario: All three pass

- **GIVEN** ready_status=pass, publishable_status=pass, source_fidelity_status=pass
- **WHEN** the gate composes the final status
- **THEN** final publishable SHALL be pass.

#### Scenario: Source-fidelity degraded, others pass

- **GIVEN** ready_status=pass, publishable_status=pass, source_fidelity_status=degraded
- **WHEN** the gate composes the final status
- **THEN** final publishable SHALL be degraded
- **AND** a publication warning SHALL be surfaced.

#### Scenario: Source-fidelity blocked, others pass, no reconciliation

- **GIVEN** ready_status=pass, publishable_status=pass, source_fidelity_status=blocked
- **AND** no accepted final reconciliation report exists
- **WHEN** the gate composes the final status
- **THEN** final publishable SHALL be blocked
- **AND** a publication blocker SHALL be surfaced.

#### Scenario: Source-fidelity blocked, others pass, reconciliation accepted

- **GIVEN** ready_status=pass, publishable_status=pass, source_fidelity_status=blocked
- **AND** accepted final reconciliation reports `source_fidelity_effective_status=reconciled_degraded`
- **WHEN** the gate composes the final status
- **THEN** final publishable SHALL be pass or degraded according to playable-publication reporting rules
- **AND** source-fidelity diagnostics SHALL remain visible as reconciled/degraded, not clean pass.

#### Scenario: Publishability already blocked

- **GIVEN** ready_status=pass, publishable_status=blocked, source_fidelity_status=pass
- **WHEN** the gate composes the final status
- **THEN** final publishable SHALL be blocked
- **AND** existing publishability blockers SHALL be preserved.

### Requirement: Source-fidelity unknown SHALL fail open

When source-fidelity status is `unknown` (legacy modules or missing accurate-ingest artifacts), it SHALL NOT block publication or degrade the final status.

#### Scenario: Legacy module with unknown source-fidelity

- **GIVEN** ready_status=pass, publishable_status=pass, source_fidelity_status=unknown
- **WHEN** the gate composes the final status
- **THEN** final publishable SHALL be pass
- **AND** no source-fidelity warnings or blockers SHALL be surfaced.

#### Scenario: Legacy module with existing publishability issues

- **GIVEN** ready_status=pass, publishable_status=degraded, source_fidelity_status=unknown
- **WHEN** the gate composes the final status
- **THEN** final publishable SHALL be degraded
- **AND** source-fidelity SHALL NOT add additional warnings.

### Requirement: Feature flag SHALL control source-fidelity enforcement

When `ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK` is `False`, source-fidelity status SHALL degrade to `unknown` for all modules, effectively disabling enforcement.

#### Scenario: Feature flag disabled

- **GIVEN** ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK is False
- **WHEN** publication gate composition runs
- **THEN** source_fidelity_status SHALL be treated as unknown
- **AND** no source-fidelity benchmark SHALL be executed.

#### Scenario: Feature flag enabled

- **GIVEN** ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK is True
- **WHEN** publication gate composition runs
- **THEN** source-fidelity benchmark SHALL execute and contribute to final status.

### Requirement: Degraded source-fidelity SHALL allow publication with operator waiver

When source-fidelity is `degraded` but all other gates pass, publication SHALL be allowed with an explicit operator waiver recorded in publication metadata.

#### Scenario: Operator accepts degraded fidelity

- **GIVEN** source-fidelity is degraded with all other gates passing
- **WHEN** the operator reviews and accepts the degradation
- **THEN** publication SHALL be allowed
- **AND** waiver SHALL be logged in publication metadata.

#### Scenario: Operator does not waive degraded fidelity

- **GIVEN** source-fidelity is degraded with all other gates passing
- **WHEN** the operator does not accept the degradation
- **THEN** publication SHALL remain degraded (not blocked)
- **AND** the module SHALL remain publishable with warning.
