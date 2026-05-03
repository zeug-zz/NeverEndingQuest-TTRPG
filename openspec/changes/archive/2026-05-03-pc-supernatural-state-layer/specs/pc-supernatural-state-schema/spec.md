## ADDED Requirements

### Requirement: PC supernatural state shall be separate from life state

The character schema SHALL support durable PC supernatural state without expanding `status` beyond the existing mechanical life-state values.

#### Scenario: Playable corrupted PC remains mechanically alive
- GIVEN a PC has positive HP and remains playable after a corruption event
- WHEN the character file records the durable corruption
- THEN `status` SHALL remain `alive`
- AND the corruption SHALL be represented in `supernaturalStates`
- AND normalization SHALL NOT require or create `status: corrupted`

#### Scenario: Playable undead PC remains mechanically active
- GIVEN a PC is returned as a playable undead character
- WHEN the character file records the durable undeath
- THEN `status` SHALL be `alive`
- AND `creatureTypes` SHALL include `undead`
- AND the PC SHALL NOT use `status: dead` to represent playable undeath

### Requirement: Character schema shall permit durable creature type and supernatural state records

Character files SHALL permit `creatureTypes` as a list of strings and `supernaturalStates` as a list of structured state records.

#### Scenario: Supernatural state record is schema-valid
- WHEN a PC has a supernatural state record
- THEN the record SHALL support `id`, `label`, `category`, `source`, `playable`, `mechanicalEffects`, `narrativeEffects`, and `removal`
- AND schema validation SHALL accept the character file without relying on private ad-hoc fields

#### Scenario: Ordinary PC remains valid
- WHEN a legacy or ordinary PC omits `creatureTypes` and `supernaturalStates`
- THEN schema validation and runtime loading SHALL remain backward compatible
- AND existing life-state behavior SHALL remain unchanged

### Requirement: Supernatural metadata migration shall preserve explicit source and consequences

Existing ad-hoc supernatural metadata SHALL be converted or superseded by schema-valid `supernaturalStates` before the runtime relies on it as durable PC state.

#### Scenario: Corrupted resurrection metadata exists
- GIVEN a character has private `_supernatural_metadata` from a prior corrupted resurrection
- WHEN migration or repair is applied
- THEN the durable state SHALL be represented in `supernaturalStates`
- AND source and consequence details SHALL be preserved when available
- AND private metadata SHALL NOT be required for future prompt or UI projection

### Requirement: Supernatural mechanical effects shall not imply automatic rules enforcement

Supernatural state `mechanicalEffects` SHALL be explicit descriptors unless deterministic enforcement for a given effect is implemented and tested.

#### Scenario: Resistance listed as descriptive state
- GIVEN a PC supernatural state lists resistance to necrotic damage
- WHEN combat or character context is generated
- THEN the context MAY surface the listed effect
- BUT damage application SHALL NOT automatically enforce that resistance unless deterministic resistance handling supports it
