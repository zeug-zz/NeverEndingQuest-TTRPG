## ADDED Requirements

### Requirement: PC_PHASE natural-language parser SHALL handle only complete supported actions

Multi-PC combat SHALL support a conservative parser for simple complete PC_PHASE natural-language actions and SHALL fall back to the existing combat LLM for ambiguous or unsupported actions.

#### Scenario: Weapon attack with supplied roll is parsed

- **GIVEN** combat is in PC_PHASE
- **AND** the acting PC is clear
- **WHEN** the facilitator enters a weapon attack description with a unique target and supplied attack roll
- **THEN** the parser SHALL resolve hit or miss using known target AC
- **AND** if the attack hits without supplied damage, it SHALL request or prefill damage rather than inventing damage
- **AND** if the attack misses, it MAY use deterministic miss narration without full combat LLM

#### Scenario: Ambiguous weapon attack falls back

- **GIVEN** combat is in PC_PHASE
- **WHEN** a weapon attack description omits the attack roll or has ambiguous target identity
- **THEN** the parser SHALL NOT apply mechanics
- **AND** runtime SHALL fall back to existing combat LLM handling or user-safe clarification

### Requirement: Explicit Magic Missile allocation SHALL be deterministically applicable

Magic Missile prose SHALL be fast-path eligible only when target allocation and damage amounts are explicit.

#### Scenario: Magic Missile with explicit dart allocation

- **GIVEN** combat is in PC_PHASE
- **AND** the caster has an available spell slot or valid casting source
- **WHEN** the facilitator states Magic Missile targets and exact dart damage values
- **THEN** enemy damage SHALL be applied through deterministic encounter mutation
- **AND** caster spell slot spend SHALL be applied through deterministic character mutation where supported
- **AND** the parser SHALL emit mechanical report and spoken narration without full combat LLM

#### Scenario: Magic Missile with unclear allocation falls back

- **WHEN** Magic Missile prose does not clearly map damage amounts to targets
- **THEN** parser SHALL NOT guess allocation
- **AND** runtime SHALL fall back to full combat LLM handling or clarification

### Requirement: Explicit healing SHALL be deterministically applicable

Healing prose SHALL be fast-path eligible only when target and healing amount are explicit and the target is a PC or allied NPC.

#### Scenario: Cure Wounds with explicit healing amount

- **GIVEN** combat is in PC_PHASE
- **AND** the caster has an available spell slot or valid casting source
- **WHEN** the facilitator states Cure Wounds target and healing amount
- **THEN** target HP SHALL be updated through deterministic character mutation where supported
- **AND** caster spell slot spend SHALL be recorded through deterministic character mutation where supported
- **AND** movement flavor MAY be narrated without separate mechanical mutation

#### Scenario: Healing a dead PC falls back

- **GIVEN** the target is mechanically dead
- **WHEN** prose attempts ordinary healing without a valid resurrection action
- **THEN** parser SHALL NOT clear death state
- **AND** runtime SHALL fall back or surface user-safe guidance

### Requirement: Movement-only prose SHALL not invent mechanical state

Movement or retreat prose SHALL be fast-path eligible as narration-only unless a later spatial system provides authoritative position mutation.

#### Scenario: Retreat behind shield wall

- **WHEN** the facilitator enters movement-only prose such as retreating behind the shield wall
- **THEN** parser MAY emit deterministic movement narration
- **AND** it SHALL NOT mutate HP, slots, enemy state, or position fields that are not authoritative

## MODIFIED Requirements

### Requirement: Parser fast path SHALL integrate with PC_PHASE event ledger when available

Parsed deterministic actions SHALL produce ledger events when the event ledger capability is present.

#### Scenario: Parsed spell damage records a ledger event

- **WHEN** parser deterministically applies spell damage
- **THEN** it SHALL record a historical already-applied ledger event if the PC_PHASE ledger is available
