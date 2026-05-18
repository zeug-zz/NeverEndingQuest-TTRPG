## ADDED Requirements

### Requirement: Numillian benchmark fixture SHALL define explicit source-fidelity expectations

The Numillian benchmark fixture SHALL define per-category expectations and thresholds derived from direct source comparison of The Hidden City of Numillian.

#### Scenario: NPC preservation expectations defined

- **GIVEN** the Numillian source contains 20 named NPCs
- **WHEN** the benchmark fixture is loaded
- **THEN** `total_source_npcs` SHALL be 20
- **AND** `minimum_represented` SHALL be 20
- **AND** `allow_minor_unused` SHALL be true.

#### Scenario: Location preservation expectations defined

- **GIVEN** the Numillian source contains 13 named locations
- **WHEN** the benchmark fixture is loaded
- **THEN** `total_source_locations` SHALL be 13
- **AND** `minimum_preserved` SHALL be 13.

#### Scenario: Puzzle preservation expectations defined

- **WHEN** the benchmark fixture is loaded
- **THEN** `required_puzzles` SHALL include `skull_riddle`, `flooding_room`, `kill_the_dog_mindscape`.

#### Scenario: Lore preservation expectations defined

- **WHEN** the benchmark fixture is loaded
- **THEN** `required_elements` SHALL include `gatepact`, `kobe_protection`.

#### Scenario: Tone preservation expectations defined

- **WHEN** the benchmark fixture is loaded
- **THEN** `expected_tone` SHALL be `quirky_character_driven_hidden_city`
- **AND** `blocked_replacement` SHALL be `generic_conspiracy_thriller`.

### Requirement: Numillian benchmark fixture SHALL define publication thresholds

The fixture SHALL define explicit pass and degraded thresholds per category for composition with the publication gate.

#### Scenario: Pass thresholds are at 100% for core categories

- **WHEN** the benchmark fixture is loaded
- **THEN** pass thresholds SHALL require 100% for NPC, location, puzzle, and lore preservation.

#### Scenario: Degraded thresholds allow some loss

- **WHEN** the benchmark fixture is loaded
- **THEN** degraded thresholds SHALL allow 85% for NPC and location
- **AND** 67% for puzzles
- **AND** 50% for lore.

#### Scenario: Tone threshold uses string match

- **WHEN** the benchmark fixture is loaded
- **THEN** tone pass SHALL require matching `quirky_character_driven_hidden_city`
- **AND** tone degraded SHALL be any tone not matching the blocked replacement.
