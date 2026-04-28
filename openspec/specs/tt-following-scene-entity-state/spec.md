## Purpose

Define persistent follower state for scene entities that travel with the party, with location exclusivity recognition, and explicit non-combat-valid default behavior.

## Requirements

### Requirement: Durable following scene entities shall require explicit follower state

The runtime SHALL represent scene entities that follow, haunt, stalk, or accompany the party with explicit persistent follower state.

#### Scenario: Scene anchor is promoted to follower
- GIVEN a location-bound scene anchor exists
- WHEN an explicit follower creation or promotion path is used
- THEN runtime state SHALL record anchor identity, display name, origin location, current location, follower behavior, source, and combat-validity status

#### Scenario: Dream or foreshadowing does not create follower
- WHEN narration frames an entity as dream, echo, omen, distant sign, or foreshadowing
- THEN no follower state SHALL be required

### Requirement: Location exclusivity shall recognize authorized followers

The narrator location exclusivity guard SHALL allow present-scene claims for authorized follower entities at their recorded current location.

#### Scenario: Authorized follower at current location
- GIVEN a scene follower record has `currentLocationId` equal to the party current location
- WHEN narration instantiates that follower as present
- THEN location exclusivity validation SHALL pass for that follower

#### Scenario: Non-following anchor remains blocked
- GIVEN a scene anchor remains bound to another location
- AND no follower state authorizes current-location presence
- WHEN narration instantiates that anchor as present at the current location
- THEN location exclusivity validation SHALL fail closed

### Requirement: Scene followers shall not be automatically combat-valid

Following scene entity state SHALL NOT make an entity a PC, party NPC, monster, or combatant by default.

#### Scenario: Follower appears in combat request without combat validity
- GIVEN a scene follower has `combatValid: false`
- WHEN a response attempts to use that follower as a combat monster or combatant
- THEN scene-entity combat validity checks SHALL reject or require explicit promotion/proxy support
