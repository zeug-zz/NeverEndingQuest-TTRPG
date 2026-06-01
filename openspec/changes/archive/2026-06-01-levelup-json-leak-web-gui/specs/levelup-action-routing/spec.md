## ADDED Requirements

### Requirement: Level-up updateCharacterInfo routed through process_action
When `LevelUpSession.handle_input()` successfully extracts and applies an `updateCharacterInfo` action from the level-up LLM response, the action SHALL be injected into the main conversation history via the standard `process_action()` pipeline for conversation state consistency.

#### Scenario: Character update recorded in conversation history
- **WHEN** the level-up LLM returns a valid `updateCharacterInfo` action
- **THEN** the action SHALL be recorded in the main conversation history
- **THEN** the character file SHALL be updated with the level-up changes

#### Scenario: Character update persistence matches standard pipeline
- **WHEN** a level-up character update is applied
- **THEN** the character file SHALL contain the same fields and values as if the update had been processed through the normal narrator action path

### Requirement: No double character update
The level-up flow SHALL apply character changes exactly once. The `update_character_info()` call in `LevelUpSession.handle_input()` is the authoritative apply point. The `process_action()` routing SHALL be used only for conversation history injection and UI state synchronization, NOT for re-applying character changes.

#### Scenario: Character HP updated exactly once
- **WHEN** a level-up increases max HP from 9 to 21
- **THEN** the character file SHALL show `maxHitPoints: 21` after the level-up completes
- **THEN** no second update SHALL overwrite or duplicate the change

### Requirement: Dead level_up_summaries code removal
The `level_up_summaries` injection path at `main.py:4696-4712` SHALL be removed, as the attribute is never populated and the code is unreachable.

#### Scenario: No level_up_summaries attribute access
- **WHEN** `process_action()` completes
- **THEN** no code path SHALL attempt to read `action_handler.level_up_summaries`
