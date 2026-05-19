## ADDED Requirements

### Requirement: Accurate-ingest SHALL produce a blueprint v2 build contract

Accurate-ingest GUI builds SHALL produce a `builder_blueprint.json` artifact with version `source_faithful_builder_blueprint.v2` before module materialization begins.

#### Scenario: Blueprint v2 contains required source-lock sections

- **GIVEN** an accurate-ingest workspace has source graph, identity, topology, normalized packet, and fidelity artifacts
- **WHEN** blueprint v2 generation runs
- **THEN** the blueprint SHALL include `module`, `source_lock`, `area_plan`, `location_roster`, `npc_roster`, `plot_graph`, `puzzle_graph`, `clue_graph`, `encounter_plan`, `item_roster`, and `enrichment_allowlist`
- **AND** it SHALL include artifact refs to the source graph and fidelity inputs.

#### Scenario: Source locks forbid replacement behavior

- **GIVEN** a blueprint v2 artifact is generated
- **WHEN** its `source_lock` section is inspected
- **THEN** `canonical_names_locked`, `required_atom_omission_blocks_build`, `invented_major_entities_forbidden`, `replacement_plotlines_forbidden`, and `puzzle_rule_rewrite_forbidden` SHALL be true.

### Requirement: Blueprint v2 SHALL preserve deterministic source structure

The blueprint SHALL preserve source order, original names, source refs, and criticality for required locations, NPCs, plot beats, puzzles, clues, encounters, and items when those facts exist in source artifacts.

#### Scenario: Map-key source locations are preserved

- **GIVEN** a source contains 13 map-key locations in source order
- **WHEN** blueprint v2 is generated
- **THEN** `location_roster` SHALL contain those 13 source locations
- **AND** each location SHALL preserve original source name, map-key number, source order, and source refs.

#### Scenario: Required puzzle facts are represented

- **GIVEN** source graph or topology artifacts identify a required puzzle with setup, rules, and solution
- **WHEN** blueprint v2 is generated
- **THEN** `puzzle_graph` SHALL include a puzzle node with those facts and source refs
- **AND** puzzle rule rewrite SHALL be forbidden by source lock.

### Requirement: Blueprint v2 validation SHALL fail closed for missing required structure

Blueprint validation SHALL return blocked or failed status when required source atoms are missing from the blueprint.

#### Scenario: Required location missing

- **GIVEN** the source graph has a required location atom
- **AND** the blueprint location roster omits it
- **WHEN** blueprint v2 validation runs
- **THEN** it SHALL return a blocker identifying the missing source atom
- **AND** the blueprint SHALL NOT be eligible for module seeding.

#### Scenario: Legacy v1 blueprint remains compatible

- **GIVEN** a workspace has only a v1 blueprint narrative handoff
- **WHEN** blueprint v2 feature flags are disabled
- **THEN** existing v1 behavior SHALL remain available
- **AND** the v2 validator SHALL NOT force legacy workspaces to fail.
