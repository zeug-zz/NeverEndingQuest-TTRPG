## ADDED Requirements

### Requirement: PC-phase deterministic command outcomes SHALL support a no-LLM fast path

Multi-PC PC_PHASE deterministic slash commands SHALL be able to complete locally without invoking the full combat LLM or combat validation LLM when the command result is mechanically complete and the fast-path feature flag is enabled.

#### Scenario: Attack miss resolves locally

- **GIVEN** multi-PC combat is in PC_PHASE
- **AND** `COMBAT_FAST_DETERMINISTIC_NARRATION` is enabled
- **WHEN** the facilitator enters `/att skeleton 9 axe`
- **AND** Python resolves the target AC as greater than 9
- **THEN** the command SHALL emit a `[skipTTS]` mechanical miss report
- **AND** it SHALL emit a separate spoken deterministic narration line
- **AND** it SHALL NOT call the combat generation LLM
- **AND** it SHALL NOT call the combat validation LLM

#### Scenario: Damage result resolves locally

- **GIVEN** multi-PC combat is in PC_PHASE
- **AND** a prior `/att` selected a valid target
- **AND** `COMBAT_FAST_DETERMINISTIC_NARRATION` is enabled
- **WHEN** the facilitator enters `/dmg 8 axe`
- **THEN** Python SHALL apply the damage to the target state
- **AND** it SHALL emit a `[skipTTS]` mechanical HP report
- **AND** it SHALL emit a separate spoken deterministic narration line
- **AND** it SHALL NOT call the combat generation LLM
- **AND** it SHALL NOT call the combat validation LLM

### Requirement: Deterministic command narration SHALL separate mechanical truth from spoken narration

Fast-path command output SHALL keep operator/mechanical reporting distinct from DM Voice narration.

#### Scenario: Mechanical report is not spoken

- **WHEN** a fast-path command emits the mechanical report
- **THEN** the mechanical report SHALL include `[skipTTS]`
- **AND** the report SHALL include relevant committed facts such as roll vs AC or HP before/after

#### Scenario: Spoken narration is TTS eligible

- **WHEN** a fast-path command emits deterministic narration
- **THEN** the narration SHALL NOT include `[skipTTS]`
- **AND** it SHALL use only committed facts from the command result
- **AND** it SHALL NOT introduce new mechanical outcomes

### Requirement: Fast-path fallback SHALL preserve existing behavior

The deterministic PC command fast path SHALL be feature-flagged so existing LLM narration behavior can be restored without changing command syntax.

#### Scenario: Fast path disabled

- **GIVEN** `COMBAT_FAST_DETERMINISTIC_NARRATION` is disabled
- **WHEN** a supported command such as `/att` miss or `/dmg` is processed
- **THEN** runtime SHALL preserve the pre-existing LLM fall-through behavior
- **AND** command syntax SHALL remain unchanged

## MODIFIED Requirements

### Requirement: Already-applied deterministic combat messages SHALL remain replay-safe

Already-applied command results SHALL remain unambiguous and SHALL NOT be interpreted as instructions for the LLM to re-apply mechanics.

#### Scenario: Fast-path damage does not produce duplicate enemy ops

- **GIVEN** `/dmg` fast path applies enemy damage in Python
- **WHEN** the next combat LLM call occurs later in the encounter
- **THEN** prior fast-path narration SHALL NOT require or imply a new `updateEncounter` op for the same damage
