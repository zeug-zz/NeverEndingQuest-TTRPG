## ADDED Requirements

### Requirement: Builder narrative SHALL be derived from builder blueprint in blueprint handoff mode

When accurate-ingest blueprint handoff is active, `builder_narrative.md` SHALL be serialized from `builder_blueprint.json` rather than generated as a short freeform summary.

#### Scenario: Source-locked narrative is generated

- **GIVEN** `builder_blueprint.json` has status `ready`
- **WHEN** builder narrative generation runs
- **THEN** `builder_narrative.md` SHALL include a `SOURCE-FAITHFUL BUILD LOCK` section
- **AND** it SHALL include required source locations, NPCs, plot topology, puzzle/trial rules, clue graph, encounter/monster plan, item plan, tone profile, forbidden inventions, and allowed compression notes.

#### Scenario: Exact source names are present

- **GIVEN** the blueprint contains required source NPC and location names
- **WHEN** source-locked narrative is serialized
- **THEN** those exact names SHALL appear in the narrative
- **AND** the narrative SHALL NOT replace them with generic equivalents.

### Requirement: Builder narrative SHALL include explicit source-lock instructions

The builder narrative SHALL tell downstream builder stages which transformations are forbidden.

#### Scenario: Forbidden replacement guidance is present

- **GIVEN** source-lock settings forbid invented major entities and replacement plotlines
- **WHEN** source-locked narrative is serialized
- **THEN** the narrative SHALL state that canonical source names are locked
- **AND** it SHALL state that invented major factions, villains, locations, and replacement plotlines are forbidden unless explicitly source-supported.

#### Scenario: Puzzle rule rewrite is forbidden

- **GIVEN** the blueprint contains source-defined puzzle or trial rules
- **WHEN** source-locked narrative is serialized
- **THEN** the narrative SHALL state that puzzle/trial setup, rules, solutions, and failure consequences must be preserved.

### Requirement: Legacy concise narrative behavior SHALL remain available outside blueprint mode

Blueprint narrative serialization SHALL not break existing workspaces or disabled feature-flag behavior.

#### Scenario: Blueprint mode disabled

- **GIVEN** accurate-ingest blueprint handoff is disabled
- **WHEN** normalization/build preparation persists builder narrative
- **THEN** existing legacy narrative generation behavior MAY be used
- **AND** no blueprint artifact SHALL be required for legacy handoff.
