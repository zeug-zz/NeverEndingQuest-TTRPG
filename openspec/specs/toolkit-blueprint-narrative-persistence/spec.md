## Purpose

Ensure ready blueprint-derived narratives remain the final persisted `builder_narrative.md` artifact and are not overwritten by legacy narrative generation during normalizer success paths.

## Requirements

### Requirement: Ready blueprint narrative SHALL remain the final persisted builder narrative

When source-blueprint handoff is ready, the normalizer SHALL persist the blueprint-derived narrative as the final `builder_narrative.md` artifact.

#### Scenario: Ready blueprint narrative is not overwritten

- **GIVEN** blueprint handoff is enabled
- **AND** `builder_blueprint.json` is generated with status `ready`
- **WHEN** normalizer success artifact persistence completes
- **THEN** `builder_narrative.md` SHALL contain `SOURCE-FAITHFUL BUILD LOCK`
- **AND** it SHALL NOT be overwritten by the legacy `_build_builder_narrative(...)` output.

#### Scenario: Normalizer result matches persisted narrative

- **GIVEN** blueprint handoff is ready
- **WHEN** normalizer returns a success result
- **THEN** the returned `builder_narrative` SHALL match the persisted blueprint-derived narrative
- **AND** the result or report SHALL expose enough metadata to identify the narrative source as source-blueprint or blueprint-derived.

### Requirement: Legacy narrative SHALL remain available when blueprint is not selected

The normalizer SHALL preserve legacy builder narrative behavior when blueprint handoff is disabled or not selected for a legacy-compatible workspace.

#### Scenario: Legacy mode persists legacy narrative

- **GIVEN** blueprint handoff is disabled or not applicable
- **WHEN** normalizer success artifact persistence completes
- **THEN** `builder_narrative.md` SHALL be generated from the legacy builder narrative path
- **AND** no source-blueprint readiness SHALL be claimed.
