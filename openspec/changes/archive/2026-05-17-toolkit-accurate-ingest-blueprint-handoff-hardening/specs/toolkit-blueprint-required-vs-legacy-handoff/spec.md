## ADDED Requirements

### Requirement: Packet builder SHALL distinguish blueprint-required workspaces from legacy workspaces

Packet builder handoff SHALL classify workspaces before executor invocation so accurate-ingest workspaces cannot silently fall back to legacy narrative when blueprint artifacts are missing or non-ready.

#### Scenario: Ready blueprint uses source-blueprint handoff

- **GIVEN** blueprint handoff is enabled
- **AND** ready `builder_blueprint.json` and `builder_blueprint_report.json` exist
- **WHEN** packet builder prepares `builder_input.json`
- **THEN** it SHALL set `handoff_mode` to `source_blueprint`
- **AND** it SHALL include blueprint path, fidelity status, source lock settings, and source artifact references.

#### Scenario: Non-ready blueprint report fails closed

- **GIVEN** blueprint handoff is enabled
- **AND** `builder_blueprint_report.json` exists with status `blocked_by_fidelity`, `missing_artifacts`, or `generation_failed`
- **WHEN** packet builder execution is requested
- **THEN** build execution SHALL fail closed before executor invocation
- **AND** the result SHALL include a reviewable `blueprint_not_ready` reason.

#### Scenario: Missing blueprint in accurate-ingest workspace fails closed

- **GIVEN** blueprint handoff is enabled
- **AND** accurate-ingest evidence exists, such as `source_graph.json` or `normalization_fidelity_report.json`
- **AND** ready blueprint artifacts are missing
- **WHEN** packet builder execution is requested
- **THEN** build execution SHALL fail closed before executor invocation
- **AND** it SHALL NOT use legacy `builder_narrative.md` as a fallback.

#### Scenario: Legacy workspace remains compatible

- **GIVEN** a workspace has no accurate-ingest source/fidelity artifacts
- **AND** ready blueprint artifacts are absent
- **WHEN** packet builder execution is requested with a valid approved packet and legacy narrative
- **THEN** existing legacy builder input and narrative behavior SHALL remain available.

#### Scenario: Disabled blueprint handoff uses legacy path

- **GIVEN** blueprint handoff is disabled
- **WHEN** packet builder execution is requested
- **THEN** absence of blueprint artifacts SHALL NOT block legacy packet-builder behavior.
