## ADDED Requirements

### Requirement: Builder input SHALL include blueprint handoff metadata when blueprint mode is active

The packet builder handoff SHALL record blueprint path, narrative path, fidelity status, source-lock settings, and source artifact references in `builder_input.json` when source-blueprint handoff is active.

#### Scenario: Builder input records source-blueprint handoff

- **GIVEN** `builder_blueprint.json` is ready
- **AND** source-locked `builder_narrative.md` exists
- **WHEN** packet builder prepares `builder_input.json`
- **THEN** `builder_input.json` SHALL include `handoff_mode: "source_blueprint"`
- **AND** it SHALL include blueprint path, builder narrative path, blueprint status, fidelity status, source lock settings, and source artifact references.

#### Scenario: Builder narrative reader prefers blueprint narrative

- **GIVEN** builder input handoff mode is `source_blueprint`
- **AND** blueprint status is ready
- **WHEN** builder execution reads narrative input
- **THEN** it SHALL read the blueprint-derived `builder_narrative.md`
- **AND** it SHALL NOT silently fall back to a lossy legacy summary.

### Requirement: Packet builder SHALL refuse required blueprint handoff when blueprint is not ready

The packet builder SHALL not proceed in accurate-ingest blueprint mode if blueprint status is not ready.

#### Scenario: Blueprint required but blocked

- **GIVEN** accurate-ingest blueprint handoff is required
- **AND** blueprint status is `blocked_by_fidelity`, `missing_artifacts`, or `generation_failed`
- **WHEN** packet builder execution is requested
- **THEN** build execution SHALL fail closed with a reviewable reason
- **AND** it SHALL NOT call `ModuleBuilder.build_module(...)` with legacy fallback narrative.

#### Scenario: Legacy workspace remains compatible

- **GIVEN** an old workspace lacks blueprint artifacts
- **AND** accurate-ingest blueprint handoff is disabled or not required
- **WHEN** packet builder execution is requested
- **THEN** existing builder input and narrative behavior SHALL remain available.

### Requirement: Builder input SHALL preserve future audit hooks

Builder input metadata SHALL include enough source-lock and artifact identity data for later build-time fidelity gates.

#### Scenario: Later gate can identify blueprint source

- **GIVEN** builder input is generated in source-blueprint mode
- **WHEN** a later build-time fidelity gate inspects it
- **THEN** it SHALL be able to identify the blueprint artifact, fidelity report, normalized packet, source graph, and source lock settings.
