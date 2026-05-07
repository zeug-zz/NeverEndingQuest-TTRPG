## ADDED Requirements

### Requirement: Multi-PC combat SHALL gate death saving throws in Python

The multi-PC combat runtime SHALL detect PCs at 0 HP who require death saving throws at PC phase start and SHALL resolve those rolls deterministically before invoking LLM combat narration or permitting `/end`.

#### Scenario: PC reduced to 0 HP receives deterministic prompt

- **GIVEN** Acheron is a player character in active multi-PC combat
- **AND** Acheron's HP is reduced to `0`
- **AND** Acheron has fewer than three death-save successes and fewer than three death-save failures
- **WHEN** combat enters the next `PC_PHASE` after Acheron was reduced to `0 HP`
- **THEN** the runtime SHALL emit a DM-continuity death-save prompt through the normal `Dungeon Master:` output path stating that Acheron needs to roll a death saving throw
- **AND** the prompt SHALL be eligible for DM voice/TTS when enabled
- **AND** the prompt SHALL NOT include `[skipTTS]` or `[SYSTEM]` markers
- **AND** the runtime SHALL wait for a death-save roll input before allowing normal PC-phase actions to continue

#### Scenario: Natural language roll input is handled without LLM

- **GIVEN** Acheron is awaiting a death saving throw
- **WHEN** the user enters `I roll 3`
- **THEN** Python SHALL parse `3` as the natural d20 death-save roll
- **AND** Python SHALL apply one death-save failure
- **AND** the input SHALL NOT be sent to the LLM for interpretation

#### Scenario: Command roll input is handled without LLM

- **GIVEN** Acheron is awaiting a death saving throw
- **WHEN** the user enters `/death 12` or `/ds 12`
- **THEN** Python SHALL parse `12` as the natural d20 death-save roll
- **AND** Python SHALL apply one death-save success
- **AND** the input SHALL NOT be sent to the LLM for interpretation

#### Scenario: Bare numeric roll input is handled only while gated

- **GIVEN** Acheron is awaiting a death saving throw
- **WHEN** the user enters `3`
- **THEN** Python SHALL parse `3` as the natural d20 death-save roll
- **AND** Python SHALL apply one death-save failure
- **AND** the input SHALL NOT be sent to the LLM for interpretation
- **BUT WHEN** no deterministic death-save gate is active
- **THEN** bare numeric input SHALL retain existing combat input behavior and SHALL NOT be interpreted as a death saving throw

#### Scenario: Invalid roll input remains gated

- **GIVEN** Acheron is awaiting a death saving throw
- **WHEN** the user enters a missing, non-integer, or out-of-range roll
- **THEN** the runtime SHALL emit user-safe guidance for valid death-save roll input
- **AND** the runtime SHALL NOT call the LLM
- **AND** Acheron SHALL remain awaiting the death-save roll

### Requirement: Death-save outcomes SHALL follow deterministic 5e mechanics

Death-save roll application SHALL be owned by Python and SHALL update in-memory combat state and persisted character state coherently.

#### Scenario: Failed death save increments failure counter

- **GIVEN** Acheron is at `0 HP` with `deathSaves.failures == 0`
- **WHEN** Acheron rolls `3` for a death saving throw
- **THEN** Acheron's persisted `deathSaves.failures` SHALL become `1`
- **AND** Acheron SHALL remain at `0 HP`
- **AND** Acheron SHALL remain unconscious/incapacitated rather than dead

#### Scenario: Natural 1 adds two failures

- **GIVEN** Acheron is at `0 HP` with `deathSaves.failures == 0`
- **WHEN** Acheron rolls `1` for a death saving throw
- **THEN** Acheron's persisted `deathSaves.failures` SHALL become `2`

#### Scenario: Successful death save increments success counter

- **GIVEN** Acheron is at `0 HP` with `deathSaves.successes == 0`
- **WHEN** Acheron rolls `15` for a death saving throw
- **THEN** Acheron's persisted `deathSaves.successes` SHALL become `1`
- **AND** Acheron SHALL remain at `0 HP`

#### Scenario: Natural 20 restores consciousness

- **GIVEN** Acheron is at `0 HP`
- **WHEN** Acheron rolls `20` for a death saving throw
- **THEN** Acheron's persisted HP SHALL become `1`
- **AND** Acheron's persisted death-save counters SHALL reset to `0` successes and `0` failures
- **AND** Acheron SHALL no longer be gated for death saves

#### Scenario: Three failures mark death

- **GIVEN** Acheron is at `0 HP` with `deathSaves.failures == 2`
- **WHEN** Acheron rolls `2` for a death saving throw
- **THEN** Acheron's persisted `status` SHALL become `dead`
- **AND** Acheron SHALL no longer be prompted for death saves

#### Scenario: Three successes stabilize without invalid schema status

- **GIVEN** Acheron is at `0 HP` with `deathSaves.successes == 2`
- **WHEN** Acheron rolls `12` for a death saving throw
- **THEN** Acheron's in-memory combat state SHALL become stable
- **AND** Acheron's persisted character JSON SHALL remain schema-valid
- **AND** persisted `status` SHALL NOT be `stable`
- **AND** Acheron SHALL no longer be prompted for death saves while stable

### Requirement: Death-save cadence SHALL be PC-phase-aware and deterministic

The multi-PC combat runtime SHALL prompt each unstable incapacitated PC once per PC phase until they are stable, dead, or healed.

#### Scenario: Resolved death save does not prompt twice in same round

- **GIVEN** Acheron resolved a death saving throw during the current `PC_PHASE` in combat round `2`
- **AND** Acheron remains at `0 HP` with fewer than three successes and failures
- **WHEN** the combat loop reaches another input point in the same `PC_PHASE`
- **THEN** Acheron SHALL NOT be prompted for another death saving throw in that same PC phase

#### Scenario: Incapacitated PC is prompted again next round

- **GIVEN** Acheron resolved one failed death saving throw during the `PC_PHASE` in combat round `2`
- **AND** Acheron remains at `0 HP` with fewer than three failures
- **WHEN** combat enters the next `PC_PHASE`
- **THEN** Acheron SHALL be prompted for another death saving throw

#### Scenario: End command is blocked while PC-phase death saves are unresolved

- **GIVEN** Acheron is at `0 HP` with an unresolved death-save obligation for the current `PC_PHASE`
- **WHEN** the user enters `/end`
- **THEN** the runtime SHALL reject `/end` with `[skipTTS]` system-style guidance requiring unresolved death saves first
- **AND** enemy/NPC batch processing SHALL NOT begin
- **AND** the input SHALL NOT be sent to the LLM

#### Scenario: Healing clears the death-save gate

- **GIVEN** Acheron is at `0 HP` and awaiting or eligible for a death saving throw
- **WHEN** Acheron is healed to HP greater than `0`
- **THEN** Acheron's death-save counters SHALL reset
- **AND** Acheron SHALL no longer be prompted for a death saving throw

### Requirement: Normal combat commands SHALL remain blocked for unresolved death-save PCs

An incapacitated PC with an unresolved death-save gate SHALL NOT perform normal PC combat commands until the death-save roll is resolved.

#### Scenario: Attack command is blocked while death save is pending

- **GIVEN** Acheron is at `0 HP` and awaiting a death saving throw
- **WHEN** the user enters `/att goblin 15`
- **THEN** the runtime SHALL reject the command with `[skipTTS]` system-style guidance requiring the death save first
- **AND** the attack SHALL NOT be applied
- **AND** the input SHALL NOT be sent to the LLM

#### Scenario: Other PCs can continue normally

- **GIVEN** Acheron is at `0 HP`
- **AND** Merisiel is alive and active for her own PC turn
- **WHEN** Merisiel enters a valid normal combat command
- **THEN** Merisiel's command behavior SHALL remain unchanged
