## ADDED Requirements

### Requirement: Builder blueprint SHALL be generated from source-backed Phase 2-3 artifacts

The accurate-ingest builder handoff pipeline SHALL generate `builder_blueprint.json` from source graph, identity, topology, normalized packet, and fidelity artifacts rather than from freeform model prose alone.

#### Scenario: Blueprint uses source artifacts

- **GIVEN** source graph, identity report, plot topology report, normalized packet, and fidelity report artifacts exist
- **AND** final fidelity status allows builder handoff
- **WHEN** blueprint generation runs
- **THEN** `builder_blueprint.json` SHALL include source-backed module identity, area plan, location roster, NPC roster, plot graph, puzzle graph, clue graph, encounter plan, item roster, tone requirements, source locks, source refs, and warnings
- **AND** source atom IDs and original display names SHALL be preserved where available.

#### Scenario: Required source location appears in blueprint roster

- **GIVEN** a required keyed source location exists in `source_graph.json`
- **WHEN** blueprint generation succeeds
- **THEN** the location SHALL appear in `location_roster` by original source name or approved mapped equivalent
- **AND** the entry SHALL include source evidence or source atom ID.

#### Scenario: Required source NPC appears in blueprint roster

- **GIVEN** a required source NPC exists in source graph or identity artifacts
- **WHEN** blueprint generation succeeds
- **THEN** the NPC SHALL appear in `npc_roster`
- **AND** aliases and original display names SHALL be preserved where available.

### Requirement: Blueprint generation SHALL preserve source topology

The builder blueprint SHALL include source plot, puzzle, clue, and trial topology from Phase 2-3 artifacts.

#### Scenario: Source puzzle chain is represented structurally

- **GIVEN** plot topology artifacts define a source puzzle or trial chain
- **WHEN** blueprint generation succeeds
- **THEN** the chain SHALL appear in `puzzle_graph` and/or `clue_graph`
- **AND** puzzle rules, solution, failure consequences, and clue dependencies SHALL not be flattened into vague summary only.

#### Scenario: Source plot order is preserved

- **GIVEN** source plot topology defines mainline beats with order or dependencies
- **WHEN** blueprint generation succeeds
- **THEN** `plot_graph` SHALL preserve that order or dependency structure
- **AND** missing transitions SHALL be represented as assumptions or warnings, not invented as facts.

### Requirement: Blueprint generation SHALL report inability to preserve required source truth

Blueprint generation SHALL not silently omit required source truth.

#### Scenario: Required source atom cannot be mapped

- **GIVEN** a required source atom exists
- **AND** blueprint generation cannot map it into a blueprint section
- **WHEN** blueprint report is produced
- **THEN** `builder_blueprint_report.json` SHALL include a blocking or refusal finding
- **AND** blueprint status SHALL not be `ready` unless the omission is explicitly allowed by prior fidelity artifacts.
