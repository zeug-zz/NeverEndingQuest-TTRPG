## ADDED Requirements

### Requirement: Combat generation prompts SHALL encode phase authority without contradiction

The combat generation prompt SHALL state that `CURRENT_PHASE` is authoritative, `PC_PHASE` resolves only the active PC, and `ENEMY_PHASE` resolves the enemy/NPC batch.

#### Scenario: PC_PHASE prompt stops at active PC
- **WHEN** the prompt is read for a `PC_PHASE` turn
- **THEN** it SHALL instruct the model to resolve only the active PC marked with `[>]`
- **AND** it SHALL NOT instruct the model to continue into enemy or allied NPC turns during `PC_PHASE`

#### Scenario: ENEMY_PHASE prompt resolves batch
- **WHEN** the prompt is read for an `ENEMY_PHASE` turn
- **THEN** it SHALL instruct the model to resolve enemies and allied NPCs in batch
- **AND** it SHALL NOT prompt a PC for action except through valid pause semantics

### Requirement: Validation prompts SHALL branch by combat phase

The combat validation prompt SHALL validate `PC_PHASE` responses under active-PC rules and `ENEMY_PHASE` responses under batch rules.

#### Scenario: PC_PHASE validation accepts pause responses
- **WHEN** the response is a `requestRoll` pause for a player-facing save, ability check, skill check, or concentration save
- **THEN** the validation prompt SHALL treat the response as valid if it stops after the request
- **AND** it SHALL NOT require the rest of the round to resolve in the same response

#### Scenario: ENEMY_PHASE validation remains strict
- **WHEN** the response is an `ENEMY_PHASE` batch
- **THEN** the validation prompt SHALL require the full enemy/NPC batch to resolve before returning to PCs
- **AND** it SHALL reject stopping mid-phase

### Requirement: Prompt routing SHALL keep supported mechanics on the correct mutation surface

The combat prompts SHALL route PC/allied mechanics to `updateCharacterInfo`, enemy mechanics to `updateEncounter`, and ongoing enemy spell damage such as Spirit Guardians to `updateEncounter`.

#### Scenario: Spirit Guardians damages an enemy
- **WHEN** an enemy starts its turn in Spirit Guardians radius
- **THEN** the prompt SHALL route the damage to `updateEncounter`
- **AND** it SHALL not route the enemy damage to `updateCharacterInfo`

#### Scenario: Healing spell slot spend is recorded before healing resolves
- **WHEN** a PC casts a healing spell that requires a healing roll or explicit value later
- **THEN** the prompt SHALL allow spell slot expenditure to be recorded immediately
- **AND** it SHALL defer HP healing until the healing amount is known

### Requirement: Enemy state changes SHALL not require more than one updateEncounter per response

The validation prompt SHALL treat enemy state changes as consolidatable into at most one `updateEncounter` when such changes exist.

#### Scenario: Multiple enemy changes consolidate
- **WHEN** several enemies take damage or status changes in one enemy batch
- **THEN** the prompt SHALL allow a single consolidated `updateEncounter`
- **AND** it SHALL NOT require multiple `updateEncounter` actions for the same response
