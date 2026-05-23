## ADDED Requirements

### Requirement: Synthetic blueprint SHALL carry puzzle graph data from topology or packet artifacts

When topology or normalized packet artifacts contain puzzle or trial metadata, the synthetic blueprint fallback SHALL populate `puzzle_graph` instead of hardcoding `puzzle_graph=[]`.

The fallback SHALL prefer `plot_topology_report.json` because it is the current source of puzzle/trial/clue topology in the accurate-ingest normalization path. Packet-local puzzle fields MAY be used as fallback sources when topology data is unavailable.

#### Scenario: Plot topology with puzzle chains populates puzzle_graph

- **GIVEN** a workspace `plot_topology_report.json` with `puzzle_chains` entries
- **WHEN** `_build_synthetic_blueprint_from_packet()` runs
- **THEN** the returned blueprint SHALL include `puzzle_graph` with entries for each source puzzle.
- **AND** each puzzle entry SHALL carry at minimum `beat_id`, `name/title`, and `source_descriptions` when available.

#### Scenario: Packet puzzle fields are fallback sources

- **GIVEN** topology data is absent and the normalized packet has `puzzle_seeds`, `puzzles`, `puzzle_chains`, or `trials`
- **WHEN** the synthetic blueprint is built
- **THEN** those packet entries SHALL be converted into `puzzle_graph` entries.

#### Scenario: Packet without puzzle data logs warning

- **GIVEN** topology data is absent and the normalized packet has no puzzle keys
- **WHEN** `_build_synthetic_blueprint_from_packet()` runs
- **THEN** `puzzle_graph` SHALL be an empty list
- **AND** a warning SHALL be logged about the fidelity gap.

#### Scenario: Puzzle coverage matches puzzle_graph length

- **GIVEN** a synthetic blueprint is built with three puzzle entries
- **WHEN** blueprint coverage is computed
- **THEN** `coverage.puzzles_in_blueprint` SHALL equal `3`.

### Requirement: Numillian benchmark SHALL detect skull_riddle and kill_the_dog_mindscape

The accurate-ingest benchmark SHALL identify both the skull riddle and the dog mindscape trial as source-fidelity-preserved puzzles.

#### Scenario: skull_riddle is found after fix

- **GIVEN** the First Trial skull riddle is preserved in the generated module
- **WHEN** the Numillian benchmark runs
- **THEN** the `puzzle_preservation` category SHALL include `skull_riddle` in its `matched` list.

#### Scenario: kill_the_dog_mindscape is found after fix

- **GIVEN** the False Third Trial dog mindscape is preserved in the generated module
- **WHEN** the Numillian benchmark runs
- **THEN** the `puzzle_preservation` category SHALL include `kill_the_dog_mindscape` in its `matched` list.

#### Scenario: flooding_room remains found

- **GIVEN** the Second Trial flooding room is preserved
- **WHEN** the Numillian benchmark runs
- **THEN** `flooding_room` SHALL remain in the `matched` list
- **AND** the puzzle count SHALL be 3 or more.
