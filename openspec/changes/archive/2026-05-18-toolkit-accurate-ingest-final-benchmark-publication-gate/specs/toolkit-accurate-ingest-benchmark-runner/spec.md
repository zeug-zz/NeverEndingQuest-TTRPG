## ADDED Requirements

### Requirement: Benchmark runner SHALL accept a module-local benchmark fixture

The benchmark runner SHALL load a JSON benchmark fixture that defines expected source-fidelity thresholds per category for a specific module.

#### Scenario: Valid fixture is loaded

- **GIVEN** a benchmark fixture JSON exists for the target module
- **WHEN** the benchmark runner loads the fixture
- **THEN** it SHALL validate required fields and return the parsed fixture
- **AND** it SHALL reject fixtures missing required expectation categories.

#### Scenario: Fixture is missing

- **GIVEN** no benchmark fixture exists for the target module
- **WHEN** the benchmark runner attempts to load the fixture
- **THEN** it SHALL fail open and return a clear missing-fixture status
- **AND** it SHALL NOT crash or block execution.

### Requirement: Benchmark runner SHALL score categories deterministically

The benchmark runner SHALL compare source graph evidence against fixture thresholds for each expectation category without LLM calls.

#### Scenario: NPC preservation category scored

- **GIVEN** the source graph contains 18 NPC references
- **AND** the fixture expects minimum 85% preservation (17 of 20)
- **WHEN** the NPC category is scored
- **THEN** it SHALL return `pass` because 18 >= 17.

#### Scenario: Location preservation category scored as degraded

- **GIVEN** the source graph contains 10 location matches
- **AND** the fixture expects minimum 85% preservation (11 of 13)
- **WHEN** the location category is scored
- **THEN** it SHALL return `degraded` because 10 < 11.

#### Scenario: Puzzle preservation category scored as blocked

- **GIVEN** the source graph contains 1 of 3 required puzzles
- **AND** the fixture expects minimum 67% preservation
- **WHEN** the puzzle category is scored
- **THEN** it SHALL return `blocked` because 33% < 67%.

### Requirement: Benchmark runner SHALL compute aggregate status by worst category

The aggregate source-fidelity status SHALL be the worst per-category status with precedence: blocked > degraded > pass > unknown.

#### Scenario: One category degraded, rest pass

- **GIVEN** NPC=pass, location=degraded, puzzle=pass, lore=pass, tone=pass
- **WHEN** aggregate status is computed
- **THEN** it SHALL be `degraded`.

#### Scenario: One category blocked

- **GIVEN** NPC=pass, location=pass, puzzle=blocked, lore=degraded, tone=pass
- **WHEN** aggregate status is computed
- **THEN** it SHALL be `blocked`.

#### Scenario: All categories unknown

- **GIVEN** no source graph artifacts are available
- **WHEN** all categories return unknown
- **THEN** aggregate status SHALL be `unknown`.

### Requirement: Benchmark runner SHALL handle missing artifacts gracefully

When source graph artifacts are absent for a module, the benchmark runner SHALL return `unknown` for all categories without error.

#### Scenario: Module has no accurate-ingest artifacts

- **GIVEN** the module directory contains no source_graph.json or source_manifest.json
- **WHEN** the benchmark runner executes
- **THEN** it SHALL return `source_fidelity_status: "unknown"`
- **AND** it SHALL NOT crash or emit blocking errors.
