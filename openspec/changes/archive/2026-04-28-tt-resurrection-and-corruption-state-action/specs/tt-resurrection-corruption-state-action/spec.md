## ADDED Requirements

### Requirement: Resurrection shall require an explicit state transition

The runtime SHALL provide a dedicated `resurrectCharacter` action for reviving or corrupting mechanically dead PCs.

#### Scenario: Explicit resurrection succeeds
- GIVEN a PC is mechanically dead
- WHEN a valid resurrection transition targets that PC with required mode, source, and HP fields
- THEN the runtime SHALL clear dead status through that explicit transition
- AND SHALL reset death saves because resurrection occurred
- AND SHALL set HP to the deliberate transition value

#### Scenario: Generic HP update remains insufficient
- GIVEN a PC is mechanically dead
- WHEN a generic character update sets positive HP without the explicit resurrection transition
- THEN the runtime SHALL keep the PC mechanically dead

### Requirement: Corrupted resurrection shall persist consequences

Corrupted, undead, bargained, or otherwise altered resurrection modes SHALL persist additive metadata describing the supernatural state.

#### Scenario: Corrupted resurrection records source
- GIVEN a dead PC is returned through a corrupted altar
- WHEN the transition mode is corrupted resurrection
- THEN the character state SHALL record the source
- AND SHALL record consequence or supernatural-state metadata

#### Scenario: Missing mode or source fails
- WHEN a resurrection transition omits required mode or source
- THEN the runtime SHALL fail closed with a player-safe error
- AND SHALL NOT change dead state

### Requirement: Prompt and validation contracts shall prefer explicit transition

Prompts and validation guidance SHALL instruct the narrator to use the supported explicit transition for durable resurrection/corruption, and SHALL preserve dream/vision/separate-entity alternatives when the transition is not used.

#### Scenario: Durable return without action
- WHEN narration claims a dead PC has durably returned without the explicit transition
- THEN validation guidance SHALL request correction rather than accepting silent revival
