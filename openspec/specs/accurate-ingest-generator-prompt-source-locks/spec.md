## Purpose

Ensure ModuleBuilder sub-generator prompt/context surfaces receive source-lock guidance when source context is available, preventing LLM drift from required source names and entities.

## Requirements

### Requirement: Generator Prompt Source Locks

ModuleBuilder sub-generator prompt/context surfaces SHALL include source-lock guidance when source context is provided.

#### Scenario: Module generation receives source locks

- **GIVEN** source-enhanced builder context
- **WHEN** module overview generation prompt/context is assembled
- **THEN** it SHALL include required source names and rules against replacement factions, villains, and plotlines.

#### Scenario: Area and location generation receive source locks

- **GIVEN** source-enhanced builder context with required source locations and bindings
- **WHEN** area or location generation prompt/context is assembled
- **THEN** it SHALL include source location names, source order or grouping when available, and relevant NPC/monster/item/clue bindings when available.

#### Scenario: Plot generation receives source locks

- **GIVEN** source-enhanced builder context with plot, puzzle, and encounter material
- **WHEN** plot generation prompt/context is assembled
- **THEN** it SHALL include required plot beats, puzzle/challenge identifiers, encounter seeds, source-lock rules, and forbidden invention guidance.
