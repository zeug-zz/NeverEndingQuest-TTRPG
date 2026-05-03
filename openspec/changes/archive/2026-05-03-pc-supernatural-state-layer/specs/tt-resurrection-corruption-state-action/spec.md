## MODIFIED Requirements

### Requirement: Corrupted resurrection shall persist consequences

Corrupted, undead, bargained, or otherwise altered resurrection modes SHALL persist additive schema-valid `supernaturalStates` metadata describing the supernatural state.

#### Scenario: Corrupted resurrection records source
- GIVEN a dead PC is returned through a corrupted altar
- WHEN the transition mode is corrupted resurrection
- THEN the character state SHALL record the source in `supernaturalStates`
- AND SHALL record consequence or supernatural-state details in schema-valid fields
- AND SHALL NOT require private `_supernatural_metadata` for future runtime interpretation

#### Scenario: Playable undead resurrection records creature type
- GIVEN a dead PC is returned as a playable undead character
- WHEN the explicit resurrection transition succeeds
- THEN `status` SHALL become `alive`
- AND `creatureTypes` SHALL include `undead`
- AND `supernaturalStates` SHALL include a playable undeath or equivalent state record

#### Scenario: Missing mode or source fails
- WHEN a resurrection transition omits required mode or source
- THEN the runtime SHALL fail closed with a player-safe error
- AND SHALL NOT change dead state
