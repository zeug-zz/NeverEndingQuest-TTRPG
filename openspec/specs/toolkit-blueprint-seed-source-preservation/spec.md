# toolkit-blueprint-seed-source-preservation Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-seed-writer-completion. Update Purpose after archive.
## Requirements
### Requirement: Seed writer SHALL preserve source names before enrichment

The blueprint seed writer SHALL preserve source location names, NPC names, plot identifiers, puzzle facts, and source order before any LLM enrichment stage can run.

#### Scenario: Location names preserved

- **GIVEN** a blueprint location roster contains required source location names
- **WHEN** the seed writer generates area files
- **THEN** each required source location SHALL appear by original name or approved blueprint mapping
- **AND** the ordering SHALL follow the blueprint source order.

#### Scenario: NPC names preserved

- **GIVEN** a blueprint NPC roster contains required source NPC names
- **WHEN** the seed writer generates module context and NPC seed artifacts
- **THEN** each required NPC SHALL appear by canonical blueprint name before enrichment starts.

### Requirement: Seed writer SHALL not invent source structure

The blueprint seed writer SHALL materialize only from blueprint/source-derived rosters and SHALL NOT create replacement plotlines, replacement locations, or invented major entities.

#### Scenario: No source replacement during seed

- **GIVEN** a blueprint has source lock fields forbidding invented major entities and replacement plotlines
- **WHEN** the seed writer materializes the module
- **THEN** generated module context, area files, and plot files SHALL derive from blueprint rosters
- **AND** seed source reporting SHALL identify any missing required source atom as a blocker rather than replacing it.

