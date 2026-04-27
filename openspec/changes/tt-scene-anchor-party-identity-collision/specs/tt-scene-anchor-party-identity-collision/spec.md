## ADDED Requirements

### Requirement: Location exclusivity guard shall distinguish party names from off-location scene anchors

The narrator location exclusivity guard SHALL accept current party member names and SHALL avoid treating exact bare party-name aliases as off-location scene-anchor instantiation.

#### Scenario: Bare party name collides with off-location anchor alias
- GIVEN the current party includes `Vitreol`
- AND an off-location scene anchor has alias `Vitreol`
- WHEN current-location narration says `Vitreol wakes by the fire`
- THEN the guard SHALL NOT fail solely because of the bare `Vitreol` alias

#### Scenario: Distinctive off-location alias remains blocked
- GIVEN the current party includes `Vitreol`
- AND an off-location scene anchor has alias `corrupted Vitreol`
- WHEN current-location narration says `corrupted Vitreol stands before you`
- AND no same-response transition or movement state authorizes that presence
- THEN the guard SHALL fail closed with a location exclusivity reason

#### Scenario: Non-party off-location anchor remains blocked
- GIVEN an off-location scene anchor has alias `The Thornwraith`
- AND no current party member canonicalizes to that alias
- WHEN current-location narration instantiates `The Thornwraith` as physically present
- THEN the guard SHALL fail closed as existing behavior requires

#### Scenario: Existing callers preserve strict behavior
- WHEN `party_member_names` is omitted
- THEN the guard SHALL preserve current strict off-location anchor behavior

## MODIFIED Requirements

### Requirement: Runtime validation shall provide party identity context to location exclusivity checks

Runtime validation SHALL pass current party member names to the narrator location exclusivity guard when party tracker data is available.

#### Scenario: Runtime has party tracker data
- GIVEN runtime validation has loaded `party_tracker_data`
- WHEN it evaluates narrator location exclusivity
- THEN it SHALL provide `partyMembers` to the guard for exact bare-alias collision handling
