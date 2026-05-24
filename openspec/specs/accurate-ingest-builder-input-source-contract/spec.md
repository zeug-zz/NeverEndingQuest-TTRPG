# accurate-ingest-builder-input-source-contract

## Purpose

Ensure that the accurate-ingest ModuleBuilder handoff carries a bounded source contract before creative generation starts, enabling deterministic source-fidelity verification without live LLM calls.

## Requirements

### Requirement: Builder handoff SHALL carry source contract fields

The accurate-ingest ModuleBuilder handoff artifact SHALL include enough source truth for ModuleBuilder to receive a bounded source contract before creative generation starts.

Required fields or equivalent serialized sections SHALL include:

- source hash or source identity
- build mode
- required source NPC names
- required source location names
- required puzzle/challenge identifiers or descriptions
- tone requirements
- forbidden-invention guidance

#### Scenario: Numillian names are present before ModuleBuilder execution

- **GIVEN** a Numillian-like accurate-ingest workspace
- **WHEN** the packet builder prepares ModuleBuilder handoff
- **THEN** the persisted handoff artifact SHALL include benchmark-required source NPC names
- **AND** benchmark-required source location names
- **AND** required puzzle/challenge tokens including `skull_riddle`, `flooding_room`, or `kill_the_dog_mindscape` equivalents
- **AND** tone marker `quirky_character_driven_hidden_city` or equivalent source-tone guidance.

#### Scenario: Forbidden invention guidance is present

- **GIVEN** a source-enhanced ModuleBuilder handoff
- **WHEN** the handoff artifact is inspected
- **THEN** it SHALL include guidance forbidding replacement plotlines and invented major source entities.

### Requirement: Handoff verification SHALL be provider-free

Tests for handoff artifact content SHALL NOT require live LLM/provider calls.

#### Scenario: Handoff test uses patched executor

- **GIVEN** a test workspace and patched ModuleBuilder executor
- **WHEN** packet build is invoked
- **THEN** tests SHALL inspect persisted handoff artifacts without calling a live provider.
