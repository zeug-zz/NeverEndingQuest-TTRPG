# tt-scene-follower-thumbnail-state Specification

## Purpose
TBD - created by archiving change scene-follower-thumbnail-state. Update Purpose after archive.
## Requirements
### Requirement: Scene follower records SHALL support optional thumbnail metadata
Runtime scene follower records SHALL remain valid when they contain only the existing required fields, and MAY include optional display, media, disposition, visibility, and source identity metadata.

#### Scenario: Legacy minimal follower record remains valid
- **GIVEN** a follower record with `entity_id`, `current_location`, and `since_turn`
- **WHEN** follower state is loaded and validated
- **THEN** the record SHALL remain valid
- **AND** missing thumbnail metadata SHALL NOT break location-exclusivity behavior

#### Scenario: Metadata enriches a follower for thumbnail rendering
- **GIVEN** a follower record with `display_name`, `entity_type`, `monster_type`, `disposition`, and `visible_in_strip`
- **WHEN** the party is in the follower's current location outside combat
- **THEN** the runtime MAY use that metadata to emit a visible strip actor

### Requirement: Scene follower updates SHALL be Python-validated before persistence
The system SHALL only persist scene follower lifecycle updates after validating that the target entity, location, state, and disposition are authoritative.

#### Scenario: Grounded monster follower update succeeds
- **GIVEN** a module monster named `Corrupted Ranger Thane`
- **AND** the party is at location `NC02`
- **WHEN** the LLM emits a structured scene follower update marking Thane as a visible guarded guide at `NC02`
- **THEN** Python SHALL validate the entity and location before writing follower state
- **AND** the persisted follower record SHALL include enough metadata for monster media routing

#### Scenario: Ungrounded follower update fails closed
- **GIVEN** an entity name that is not grounded in module monsters, bestiary, module NPC authority, existing follower state, scene authority, or validated same-turn state
- **WHEN** a scene follower update attempts to persist that entity
- **THEN** the update SHALL fail without writing follower state
- **AND** the failure SHALL surface a structured reason

### Requirement: Non-combat strip SHALL render visible current-location monster followers without leaking hidden seeds
The party data socket payload SHALL include current-location visible monster-like followers in the existing non-combat hostile-presence lane, while continuing to exclude generic location monster seeds.

#### Scenario: Visible follower monster appears in strip payload
- **GIVEN** a visible follower record for `Corrupted Ranger Thane` at the party's current location
- **AND** no active combat encounter is running
- **WHEN** the party data socket payload is built
- **THEN** `location_hostiles` SHALL include Thane
- **AND** the emitted metadata SHALL use monster media lookup

#### Scenario: Generic location monster seed remains hidden
- **GIVEN** a location has a generic `monsters` list
- **AND** no explicit visible hostile metadata or visible follower record names one of those monsters
- **WHEN** the party data socket payload is built
- **THEN** those generic monster seeds SHALL NOT be emitted as `location_hostiles`

#### Scenario: Off-location follower does not appear
- **GIVEN** a visible follower record whose `current_location` does not match the party's current location
- **WHEN** the party data socket payload is built
- **THEN** that follower SHALL NOT be emitted in `location_hostiles`

### Requirement: Scene follower lifecycle cleanup SHALL prevent stale thumbnails
Follower lifecycle states that remove, hide, or transform an actor SHALL prevent stale non-combat thumbnail rendering.

#### Scenario: Released follower disappears from strip
- **GIVEN** a visible follower is currently rendered in the non-combat strip
- **WHEN** a validated update marks the follower `released`, `escaped`, `dead`, `joined_party`, `hidden`, or `combat_started`
- **THEN** the follower SHALL no longer be emitted as a visible strip actor unless another authoritative state re-adds visibility

### Requirement: Scene followers SHALL NOT become combat-valid by thumbnail visibility alone
Follower state and thumbnail visibility SHALL NOT authorize formal encounter creation or combatant hydration.

#### Scenario: Visible captive remains non-combat by default
- **GIVEN** a visible follower record for a captive monster
- **WHEN** combat creation validates monsters for an encounter
- **THEN** the follower record alone SHALL NOT make that entity combat-valid
- **AND** existing combat-validity contracts SHALL still apply

