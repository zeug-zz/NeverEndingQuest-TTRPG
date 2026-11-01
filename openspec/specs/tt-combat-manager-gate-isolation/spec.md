# tt-combat-manager-gate-isolation Specification

## Purpose
TBD - created by archiving change tt-combat-manager-hardening-only. Update Purpose after archive.
## Requirements

### Requirement: `/init` Gate Handling SHALL Be Isolated Behind a TT Helper Contract
The multi-PC two-group initiative gate handling for `/init` SHALL execute through a dedicated helper boundary instead of an inline monolithic branch.

#### Scenario: Valid `/init` request is handled through helper
- **WHEN** combat is awaiting facilitator initiative input and user submits `/init <1-20>`
- **THEN** the helper SHALL validate input, resolve winner (`pcGroup` vs `dmGroup`), and return structured handling output
- **AND** caller flow SHALL continue using helper output without duplicating winner/phase logic inline

#### Scenario: dmGroup winner preserves forced enemy-turn fall-through behavior
- **WHEN** helper resolves `dmGroup` as winner (including ties)
- **THEN** helper-driven handling SHALL preserve current behavior that sets ENEMY phase state and triggers enemy-turn fall-through handling in caller flow
- **AND** deterministic gate output contract SHALL remain compatible with existing `[skipTTS][prefill:/init ]` guidance behavior for invalid/non-`/init` gate input

#### Scenario: Invalid `/init` request is rejected deterministically
- **WHEN** user submits malformed or out-of-range `/init` input while gate is active
- **THEN** helper SHALL return a deterministic error response
- **AND** combat progression SHALL remain blocked until a valid `/init` is received

### Requirement: Initiative State Writes SHALL Preserve Existing TT Semantics
Helper-based handling SHALL preserve current TT state updates and persistence behavior.

#### Scenario: Winner and marker persistence
- **WHEN** helper resolves initiative winner
- **THEN** encounter state SHALL persist `initiativeMode`, `initiativeRolls`, `initiativeWinner`, `roundStartsWith`, and `awaitingPcGroupRoll`
- **AND** helper SHALL apply `openingEnemyBatchPending` marker via TT state sync helper

#### Scenario: Existing marker lifecycle remains intact after extraction
- **WHEN** round-start handling or opening-batch completion runs after helper extraction
- **THEN** opening marker semantics SHALL remain unchanged across `/init` resolution, round-start reapplication, and post-opening-batch clear transition back to PC phase

#### Scenario: Compatibility mirror persistence
- **WHEN** helper resolves winner and rolls
- **THEN** party tracker mirror (`worldConditions.combatInitiative`) SHALL be updated consistently with current behavior
- **AND** persistence SHALL use existing safe JSON write paths

### Requirement: TT-Only Refactor Scope SHALL Avoid Upstream Flow Drift
This extraction SHALL remain scoped to TT initiative branches in current test build.

#### Scenario: Single-player behavior remains unchanged
- **WHEN** single-player combat path executes
- **THEN** refactor SHALL not alter single-player initiative/combat flow behavior
- **AND** no TT-only helper branch SHALL be required for SP execution

### Requirement: Phase1 Normalization Ownership SHALL Follow The Combat Package
Phase1 initiative normalization SHALL be owned by the combat package, while its legacy import path and the existing TT synchronization-helper responsibilities remain compatible.

#### Scenario: Phase1 normalization resolves through old and new package paths
- **WHEN** a caller imports `normalize_phase1_initiative(...)` through the legacy combat manager path or the combat package API
- **THEN** both paths SHALL resolve to the same implementation and return contract

#### Scenario: Legacy import remains available after package relocation
- **WHEN** legacy callers use the phase1 normalization API after package decomposition
- **THEN** `normalize_phase1_initiative(...)` SHALL remain available from `core.managers.combat_manager` through its compatibility shim
- **AND** the legacy path and combat package API SHALL resolve to the same implementation and return contract

#### Scenario: Phase1 normalization preserves TT sync helper ownership
- **WHEN** phase1 initiative normalization applies round or opening-batch markers
- **THEN** marker and roster synchronization SHALL continue through the existing combat state sync contract
- **AND** encounter and party-tracker persistence behavior SHALL remain unchanged

#### Scenario: Initiative normalization behavior remains unchanged
- **WHEN** valid, missing, legacy, or inconsistent phase1 initiative state is normalized
- **THEN** the resulting initiative values, safe defaults, and phase-control behavior SHALL match the pre-decomposition behavior

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
