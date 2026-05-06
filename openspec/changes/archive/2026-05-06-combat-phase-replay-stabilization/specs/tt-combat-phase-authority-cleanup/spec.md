## ADDED Requirements

### Requirement: ENEMY_PHASE prompt context SHALL contain no active-PC action override

During ENEMY_PHASE, combat prompt context SHALL avoid marking any PC as the current legal actor and SHALL avoid critical override language instructing a PC to act.

#### Scenario: Enemy phase suppresses active PC override

- **GIVEN** combat phase is ENEMY_PHASE
- **WHEN** combat prompt context is assembled
- **THEN** no context block SHALL state `Only <PC> can act now`
- **AND** no PC SHALL be marked as `[>] CURRENT TURN`

#### Scenario: PC phase keeps active PC authority

- **GIVEN** combat phase is PC_PHASE
- **AND** Acheron is the active PC
- **WHEN** combat prompt context is assembled
- **THEN** the prompt SHALL identify Acheron as the legal active PC
- **AND** enemy/NPC batch processing SHALL NOT be instructed before Acheron's action

### Requirement: Combat prompts SHALL define phase precedence

Combat generation and validation prompts SHALL state that authoritative `CURRENT_PHASE` takes precedence over turn markers and legacy context hints.

#### Scenario: Source contract defines marker limits

- **WHEN** combat prompt source-contract tests scan the prompt files
- **THEN** `[>]` PC current-turn markers SHALL be described as PC_PHASE-only
- **AND** ENEMY_PHASE SHALL be described as an enemy/NPC batch with no active PC actor

### Requirement: Validation SHALL reject PC prompting during ENEMY_PHASE

Combat validation SHALL treat responses that ask a PC what they do during ENEMY_PHASE as invalid when authoritative phase state requires enemy/NPC batch resolution.

#### Scenario: Enemy phase asks PC to act

- **GIVEN** combat phase is ENEMY_PHASE
- **WHEN** a response resolves no required enemy/NPC batch and asks a PC for their action
- **THEN** validation SHALL reject the response with phase-correction guidance

#### Scenario: Enemy phase damages PCs as targets

- **GIVEN** combat phase is ENEMY_PHASE
- **WHEN** a response applies enemy effects to PCs as targets using `updateCharacterInfo`
- **THEN** validation SHALL NOT reject solely because PCs are update targets
