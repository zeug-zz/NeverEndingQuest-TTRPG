## ADDED Requirements

### Requirement: Final narrator actions SHALL pass through shared authority normalization

The narrator runtime SHALL normalize the final action list before action processing so unsafe same-module location writes are either converted to authoritative travel actions or rejected before persistence.

#### Scenario: No-module same-module location tracker write converts to transition

- **GIVEN** the party is in module `The_Thornwood_Watch` at location `NC02`
- **AND** a narrator response contains `updatePartyTracker` with `currentLocationId: "NC05"` and no `module` field
- **WHEN** final action normalization runs
- **THEN** the action list SHALL contain an equivalent `transitionLocation` intent for `NC05`
- **AND** the same-module location change SHALL NOT be persisted through `updatePartyTracker`

#### Scenario: Same-location tracker write strips location keys

- **GIVEN** the party is already at location `NC05`
- **AND** a narrator response contains `updatePartyTracker` with `currentLocationId: "NC05"`
- **AND** the same action contains non-location tracker fields
- **WHEN** final action normalization runs
- **THEN** location keys SHALL be removed as a no-op
- **AND** non-location tracker fields SHALL remain eligible for processing

#### Scenario: Cross-module tracker update remains valid

- **GIVEN** a narrator response contains `updatePartyTracker` with a different `module` value
- **WHEN** final action normalization runs
- **THEN** the cross-module tracker update SHALL remain processable as a tracker update

### Requirement: Party tracker merge SHALL fail closed on unsafe same-module location writes

The party tracker merge layer SHALL reject same-module location changes attempted through `updatePartyTracker` when they bypass final action normalization.

#### Scenario: Unsafe merge bypass is rejected

- **GIVEN** current party tracker state has module `The_Thornwood_Watch` and location `NC02`
- **WHEN** an `updatePartyTracker` action attempts to write `currentLocationId: "NC05"` without an allowed same-module bypass
- **THEN** the merge SHALL fail without writing `party_tracker.json`
- **AND** the caller SHALL receive structured error information suitable for user-safe feedback

#### Scenario: Non-location tracker fields still merge

- **WHEN** an `updatePartyTracker` action updates non-location world-state fields such as `resolvedHostilesByLocation`
- **THEN** those fields SHALL merge non-destructively
- **AND** the same-module location guard SHALL NOT reject the action solely because no location write is present

### Requirement: Narrator prompts SHALL reserve same-module movement for transitionLocation

Narrator and validation prompts SHALL describe `transitionLocation` as the action for same-module movement and SHALL NOT describe `updatePartyTracker` as a same-module location setter.

#### Scenario: Prompt contract prevents broad tracker movement

- **WHEN** a prompt source-contract test scans narrator action guidance
- **THEN** same-module movement SHALL be associated with `transitionLocation`
- **AND** `updatePartyTracker` SHALL be associated only with cross-module activation or tracker/world-state fields
