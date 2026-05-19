## ADDED Requirements

### Requirement: Seed writer SHALL emit downstream seed artifacts

The blueprint seed writer SHALL emit NPC and monster seed artifacts for blueprint-native accurate-ingest builds before enrichment, media prewarm, monster materialization, MMG authority, and publication workflows run.

#### Scenario: NPC seed artifact generated

- **GIVEN** a ready blueprint v2 artifact with NPC roster entries
- **WHEN** the seed writer materializes the module
- **THEN** it SHALL create `npcs_seed.json`
- **AND** the artifact SHALL include each blueprint NPC canonical name
- **AND** the artifact SHALL preserve aliases, role, faction, location binding, criticality, and source refs when available.

#### Scenario: Monster seed artifact generated

- **GIVEN** a ready blueprint v2 artifact with encounter or monster hints
- **WHEN** the seed writer materializes the module
- **THEN** it SHALL create `monsters_seed.json`
- **AND** the artifact SHALL include source monster names or materialization hints without generating monster stat files.

#### Scenario: Dry run includes seed artifacts

- **GIVEN** a ready blueprint v2 artifact
- **WHEN** the seed writer runs with `dry_run=True`
- **THEN** the planned file list SHALL include `npcs_seed.json`, `monsters_seed.json`, and `seed_source_report.json`
- **AND** no module files SHALL be written.

### Requirement: Seed writer SHALL emit source-preservation report

The blueprint seed writer SHALL emit a source-preservation sidecar report when schema-valid module files cannot carry all blueprint IDs, source order, original names, and source refs directly.

#### Scenario: Source order and refs represented

- **GIVEN** a blueprint location roster with source-ordered locations and source refs
- **WHEN** the seed writer materializes the module
- **THEN** generated area files SHALL preserve source order by location name
- **AND** `seed_source_report.json` SHALL represent source order, blueprint IDs, and source refs for later fidelity checks.
