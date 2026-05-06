## ADDED Requirements

### Requirement: Successful transitions SHALL sync traveling scene followers

After a successful party location transition, the runtime SHALL attempt to move present scene followers that are conservatively classified as traveling with the party from the old party location to the new party location.

#### Scenario: Traveling guide follows party transition

- **GIVEN** a scene follower has `lifecycle_state: "present"`
- **AND** the follower's `current_location` equals the party's old location
- **AND** the follower has a traveling disposition such as `guarded_guide`
- **WHEN** the party successfully transitions to a new location
- **THEN** the follower record SHALL be updated to the new location

#### Scenario: Location-bound follower does not teleport

- **GIVEN** a present scene follower is not classified as traveling with the party
- **WHEN** the party transitions to a new location
- **THEN** the follower record SHALL remain at its authored or current location

#### Scenario: Follower sync failure does not roll back travel

- **GIVEN** the party transition succeeds
- **WHEN** follower sync raises an exception or cannot persist follower updates
- **THEN** the transition SHALL remain successful
- **AND** the failure SHALL be logged as degraded follower sync

### Requirement: DM Note SHALL project present scene followers

DM Note generation SHALL include present scene followers at the current effective location in a compact truth-surface section independent of party NPC projection.

#### Scenario: Follower-only scene remains visible to narrator

- **GIVEN** the current location has no `partyNPCs`
- **AND** a scene follower record is present at the current location
- **WHEN** the DM Note is generated
- **THEN** the DM Note SHALL include a `SCENE FOLLOWERS PRESENT HERE` section
- **AND** the follower SHALL be listed with compact identity and disposition context

#### Scenario: Follower at another location is excluded

- **GIVEN** a scene follower record is present at a different location from the party
- **WHEN** the DM Note is generated
- **THEN** that follower SHALL NOT appear as present in the current scene follower section

### Requirement: Follower prompt contract SHALL match deterministic follower persistence

Narrator prompt guidance SHALL describe scene followers as deterministic records managed by Python and updated through follower-state actions, not as background NPC location moves unless the entity is actually a background NPC.

#### Scenario: FOLLOWER_STATE prompt references updateSceneFollower

- **WHEN** a prompt source-contract test scans `@FOLLOWER_STATE`
- **THEN** the prompt SHALL reference deterministic scene follower records or `updateSceneFollower`
- **AND** it SHALL NOT require `moveBackgroundNPC` as the persistence mechanism for scene follower location truth
