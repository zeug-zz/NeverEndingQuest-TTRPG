## Purpose

Preserve source monster references and encounter seeds in accurate-ingest builder input so ModuleBuilder has visibility into authored monster names and encounter seeds without requiring stat-file materialization.

## Requirements

### Requirement: Monster And Encounter Source Handoff

Accurate-ingest builder input SHALL preserve source monster references and encounter seeds when those fields are present in normalized packet or source blueprint artifacts.

#### Scenario: Numillian monster refs enter builder input

- **GIVEN** a Numillian-like normalized packet containing `monster_refs`
- **WHEN** source-enhanced `builder_input` is created
- **THEN** `builder_input` SHALL include `source_monster_refs`
- **AND** the list SHALL preserve source terms such as `Alhoon`, `Illithid`, `Homunculus`, `Kenku`, `Nothic`, and `Charion` when present.

#### Scenario: Numillian encounter seeds enter builder input

- **GIVEN** a Numillian-like normalized packet containing `encounter_seeds`
- **WHEN** source-enhanced `builder_input` is created
- **THEN** `builder_input` SHALL include `source_encounter_seeds`
- **AND** encounter seed text SHALL remain bounded and source-derived.

### Requirement: No Monster Stat Materialization In This Change

This change SHALL NOT require generation of `monsters/*.json` files.

#### Scenario: Monster handoff exists without stat files

- **GIVEN** source monster references are present in builder input
- **WHEN** tests verify this change
- **THEN** tests SHALL assert handoff visibility only
- **AND** tests SHALL NOT require actual monster stat-file materialization.
