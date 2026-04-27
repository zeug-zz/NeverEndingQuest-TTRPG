## ADDED Requirements

### Requirement: Narration shall preserve supernatural freedom within Python state authority

System prompts SHALL state that Python mechanical state is authoritative for HP, death, death saves, rest effects, location presence, party membership, combatant state, and persistent scene entities.

#### Scenario: Dead PC is described supernaturally without state change
- GIVEN a PC is mechanically dead
- WHEN the narrator describes dreams, echoes, visions, or spiritual impressions of that PC
- THEN the prompt contract SHALL allow that narration
- AND SHALL require it to remain subjective, symbolic, distant, or foreshadowing unless a state action changes durable reality

#### Scenario: Durable supernatural claim requires a state shape
- WHEN narration claims a dead PC is physically present, following the party, restored to life, or transformed into a durable entity
- THEN the prompt contract SHALL require a matching Python state shape or action

### Requirement: Prompts shall teach four valid death/supernatural state shapes

Prompts SHALL identify these valid shapes: dead PC remains dead, separate entity, explicit corrupted/resurrected PC, and dream/vision/echo.

#### Scenario: Dead PC remains dead
- WHEN a response keeps the PC mechanically dead
- THEN it MAY narrate grief, body transport, attempted resurrection, dreams, corruption pressure, or spirit echoes
- AND SHALL NOT imply ordinary rest or healing revived the PC

#### Scenario: Separate entity
- WHEN a response creates or references a corpse-thrall, echo, vessel, or simulacrum as durable reality
- THEN the response SHALL use appropriate existing state mechanisms for scene entity, NPC, combatant, or future follower state
- AND SHALL NOT silently replace the PC's mechanical identity

#### Scenario: Explicit corrupted or undead PC resurrection
- WHEN a response returns the PC as a playable or semi-playable character
- THEN it SHALL require explicit resurrection/corruption state transition support
- AND SHALL NOT be represented as generic HP healing

#### Scenario: Dream or foreshadowing
- WHEN no durable state action is emitted
- THEN supernatural content SHALL be framed as dream, vision, omen, echo, memory, or foreshadowing

### Requirement: Validation prompt shall request legal alternatives for unsupported durable claims

Validation prompts SHALL guide retry responses toward legal alternatives when durable supernatural claims lack matching state actions.

#### Scenario: Unsupported durable return
- WHEN a narrator response claims a dead PC has returned to life without a supported action
- THEN validation guidance SHALL request either a legal state action if available or a rewrite as dead, separate entity, or dream/vision framing
