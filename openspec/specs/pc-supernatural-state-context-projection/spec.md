# pc-supernatural-state-context-projection Specification

## Purpose
TBD - created by archiving change pc-supernatural-state-layer. Update Purpose after archive.
## Requirements
### Requirement: Supernatural states shall be visible in player-facing character surfaces

Player-facing character surfaces SHALL display durable PC supernatural state summaries when present.

#### Scenario: Character Sheet displays state badge
- GIVEN a PC has one or more `supernaturalStates`
- WHEN the Character Sheet renders that PC
- THEN it SHALL display the state label or labels
- AND it SHALL display creature type information when available
- AND it SHALL NOT replace or hide the normal life-state display

#### Scenario: Character PDF includes supernatural state summary
- GIVEN a PC has supernatural states or non-ordinary creature types
- WHEN the Character Sheet PDF is generated
- THEN the PDF SHALL include a bounded supernatural state summary
- AND the summary SHALL include source or removal guidance when available and space permits

### Requirement: Supernatural states shall be projected into narrator context

Narrator-facing context SHALL include concise supernatural state information for affected PCs so narration can honor current durable state.

#### Scenario: DM Note includes active PC supernatural state
- GIVEN the active PC has a supernatural state
- WHEN the multi-PC DM Note is built
- THEN the DM Note SHALL include state label, creature types, and concise effect summaries
- AND the line SHALL be bounded to avoid displacing core HP/status truth

#### Scenario: Conversation context includes state summary
- GIVEN a PC has a supernatural state
- WHEN conversation context is assembled
- THEN the context SHALL include a compact state summary
- AND the summary SHALL preserve the principle that Python state is mechanical truth

### Requirement: Combat context shall include relevant supernatural state truth

Combat prompt/truth context SHALL include relevant creature type and supernatural state details for touched PCs without changing turn ownership or life-state rules.

#### Scenario: Touched corrupted PC appears in combat truth pack
- GIVEN a PC with `supernaturalStates` is a touched combatant
- WHEN combat validation or simulation context is assembled
- THEN the context SHALL include the PC's creature types and supernatural state labels
- AND it SHOULD include concise mechanical effect descriptors
- AND it SHALL keep `status` as the life-state authority

#### Scenario: Untouched supernatural PC does not bloat combat context
- GIVEN a PC has supernatural state records but is not relevant to the current combat validation payload
- WHEN a compact touched-combatant truth pack is assembled
- THEN the implementation MAY omit detailed state effects for that PC
- AND SHOULD preserve enough party-level identity context to avoid misclassifying the PC as an NPC or monster

### Requirement: Projection shall preserve hidden-state scope decisions

The first implementation SHALL treat durable PC supernatural states as player-visible and SHALL NOT introduce hidden/secret supernatural state behavior.

#### Scenario: State exists on PC file
- WHEN a durable supernatural state is present in the PC file
- THEN player-facing surfaces SHALL be allowed to show it
- AND implementation SHALL NOT rely on unreviewed secret-state filtering rules

