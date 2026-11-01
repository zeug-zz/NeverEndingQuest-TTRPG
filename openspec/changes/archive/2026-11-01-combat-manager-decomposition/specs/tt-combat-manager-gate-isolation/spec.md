# Spec Delta

## MODIFIED Requirements

### Requirement: Phase1 Normalization Ownership SHALL Remain Stable In This Change

Phase1 initiative normalization SHALL follow the combat package as its implementation owner, while its legacy import path and current TT synchronization-helper responsibilities remain compatible.

#### Scenario: Phase1 normalization resolves through old and new package paths
- **WHEN** a caller imports `normalize_phase1_initiative(...)` through the legacy combat manager path or the combat package API
- **THEN** both paths SHALL resolve to the same implementation and return contract

#### Scenario: No relocation of phase1 normalization in this change
- **WHEN** legacy callers use the phase1 normalization API after package decomposition
- **THEN** `normalize_phase1_initiative(...)` SHALL remain available from `core.managers.combat_manager` through its compatibility shim
- **AND** implementation ownership MAY reside in the combat package

#### Scenario: Phase1 normalization preserves TT sync helper ownership
- **WHEN** phase1 initiative normalization applies round or opening-batch markers
- **THEN** marker and roster synchronization SHALL continue through the existing combat state sync contract
- **AND** encounter and party-tracker persistence behavior SHALL remain unchanged

#### Scenario: Initiative normalization behavior remains unchanged
- **WHEN** valid, missing, legacy, or inconsistent phase1 initiative state is normalized
- **THEN** the resulting initiative values, safe defaults, and phase-control behavior SHALL match the pre-decomposition behavior
