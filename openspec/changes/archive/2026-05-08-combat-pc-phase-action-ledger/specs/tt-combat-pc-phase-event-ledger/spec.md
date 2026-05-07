## ADDED Requirements

### Requirement: PC_PHASE events SHALL be recordable as historical metadata

Multi-PC combat SHALL support a compact PC_PHASE event ledger that records already-applied PC actions for recap, debugging, and prompt context without becoming mechanical authority.

#### Scenario: Damage event is recorded after deterministic command

- **GIVEN** multi-PC combat is in PC_PHASE
- **WHEN** `/dmg` applies damage to a target
- **THEN** the ledger SHALL record a compact event containing actor, target, event kind, damage amount, and known HP before/after
- **AND** the event SHALL mark `mechanics_already_applied` as true
- **AND** the encounter or character file SHALL remain the source of mechanical truth

#### Scenario: Miss event is recorded after deterministic attack miss

- **GIVEN** multi-PC combat is in PC_PHASE
- **WHEN** `/att` resolves a miss
- **THEN** the ledger SHALL record actor, target, weapon or attack flavor, attack roll, and target AC when known
- **AND** the event SHALL not imply any HP mutation

### Requirement: Ledger lifecycle SHALL avoid stale or duplicate recap facts

PC_PHASE ledger management SHALL prevent duplicate event recording and stale facts from contaminating later rounds or completed combat.

#### Scenario: Duplicate command event is not recorded twice

- **GIVEN** a deterministic command result has already produced a ledger event
- **WHEN** the same command result is displayed or persisted again during the same handling path
- **THEN** the ledger SHALL NOT create a duplicate event for the same mechanical result

#### Scenario: Combat completion clears active ledger state

- **WHEN** combat exits successfully
- **THEN** active in-memory PC_PHASE ledger state SHALL be cleared or marked complete
- **AND** no stale PC_PHASE facts SHALL be injected into future unrelated encounters

### Requirement: Ledger-derived prompt context SHALL be historical-only

Any PC_PHASE ledger facts injected into prompts SHALL be explicitly marked as historical-only and SHALL prohibit mechanical replay.

#### Scenario: End-phase recap context cannot replay mechanics

- **GIVEN** PC_PHASE ledger contains already-applied damage facts
- **WHEN** `/end` prepares ENEMY_PHASE context
- **THEN** any ledger-derived context SHALL state that the facts are historical only
- **AND** it SHALL instruct the LLM not to emit PC mechanics actions for those facts

## MODIFIED Requirements

### Requirement: Already-applied replay protection SHALL account for ledger facts

Deterministic replay protection SHALL treat ledger facts as already-applied historical context rather than fresh mechanics instructions.

#### Scenario: Ledger damage fact does not require updateEncounter

- **GIVEN** the ledger says a PC already dealt damage to an enemy
- **WHEN** a later ENEMY_PHASE prompt includes that fact as historical context
- **THEN** the LLM SHALL NOT be required to emit `updateEncounter` for that prior PC damage
