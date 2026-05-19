## ADDED Requirements

### Requirement: Blueprint seed writer SHALL materialize module skeletons without provider calls

The blueprint seed writer SHALL create a schema-valid skeletal module from blueprint v2 artifacts without calling LLM providers.

#### Scenario: Ready blueprint materializes core files

- **GIVEN** a ready blueprint v2 artifact with module, area, location, NPC, plot, puzzle, and map data
- **WHEN** the seed writer runs
- **THEN** it SHALL create `module_context.json`, `module_context_BU.json`, `module_plot.json`, `module_plot_BU.json`, area JSON files, and map JSON files
- **AND** it SHALL return a report listing created files and coverage counts.

#### Scenario: Dry run does not write files

- **GIVEN** a ready blueprint v2 artifact
- **WHEN** the seed writer runs with `dry_run=True`
- **THEN** it SHALL return the planned file list and coverage report
- **AND** it SHALL NOT create or modify module files.

### Requirement: Seed writer SHALL preserve source-locked names and order

The seed writer SHALL preserve required source location names, source order, NPC names, plot IDs, puzzle facts, and source-derived connectivity hints from the blueprint.

#### Scenario: Source locations are seeded before enrichment

- **GIVEN** a blueprint location roster contains source locations in source order
- **WHEN** area files are seeded
- **THEN** generated locations SHALL preserve source names and source ordering
- **AND** source names SHALL exist before any LLM enrichment pass runs.

#### Scenario: NPC roster is seeded

- **GIVEN** a blueprint NPC roster contains required and major NPCs
- **WHEN** module context is seeded
- **THEN** those NPCs SHALL be present in `module_context.json`
- **AND** their canonical names SHALL match the blueprint names.

### Requirement: Seed writer SHALL refuse invalid or blocked blueprints

The seed writer SHALL fail closed for blocked, failed, invalid, stale, or non-v2 blueprints when blueprint-native GUI build is required.

#### Scenario: Blocked blueprint refuses materialization

- **GIVEN** a blueprint has `blueprint_status: "blocked"`
- **WHEN** the seed writer is invoked
- **THEN** it SHALL return `seed_status: "blocked"`
- **AND** it SHALL NOT write module files.

#### Scenario: Existing module requires overwrite policy

- **GIVEN** a target module directory already exists
- **WHEN** the seed writer runs without approved overwrite or rebuild policy
- **THEN** it SHALL refuse to overwrite existing files
- **AND** it SHALL return a clear blocker for GUI confirmation handling.
