# combat-deterministic-enemy-resolution Specification

## Purpose
Defines which enemy attack batches Python can resolve reproducibly and when an entire batch must remain with the existing LLM combat path.

## Requirements

### Requirement: Supported enemy batches SHALL be planned as deterministic ledgers

Python SHALL derive every supported batch outcome from the authoritative pre-batch state, authored attack data, and an explicit batch seed before applying any mutation.

#### Scenario: Identical state and seed reproduce the ledger
- **WHEN** the same supported batch is planned twice from identical encounter, party, monster, and seed inputs
- **THEN** both ledgers SHALL contain identical actors, targets, attack choices, rolls, hit results, damage, and resulting HP/status values
- **AND** ledger planning SHALL perform no persistent state writes

#### Scenario: Later unsupported actor prevents partial deterministic resolution
- **WHEN** an earlier enemy in a batch has a supported attack but a later scheduled enemy requires unsupported mechanics
- **THEN** Python SHALL decline the whole batch before applying any ledger entry

### Requirement: Enemy targets SHALL be selected from existing combat order

Supported attacks SHALL select player-character candidates from the current encounter turn order, scanning after the acting enemy and wrapping at the end; repeated attacks continue after the preceding target. Only dead or defeated PCs are skipped. A selected PC with zero HP, unconscious status, death-save state, or another unsupported target modifier SHALL cause whole-batch fallback. No grid or inferred position SHALL be used.

#### Scenario: Four-PC target selection is repeatable
- **GIVEN** the same living four-PC roster and turn order
- **WHEN** the same seeded enemy batch is planned
- **THEN** the targets SHALL follow the same turn-order scan and SHALL skip only dead or defeated PCs
- **AND** any selected zero-HP or unconscious PC SHALL cause whole-batch fallback before application

#### Scenario: No resolvable target exists
- **WHEN** a scheduled attack has no uniquely resolvable target from current combat state
- **THEN** the whole batch SHALL use the existing generate-and-validate path without partial deterministic effects

### Requirement: Monster multiattack declarations SHALL be explicit

The optional monster `multiattack` field SHALL be a non-empty ordered array of objects containing an `action` string and a positive integer `count`; each action SHALL identify exactly one authored attack action. The optional encounter-combatant `leader` field SHALL be a boolean and SHALL NOT be required for legacy encounters.

#### Scenario: Declared multiattack resolves its authored sequence
- **WHEN** a monster has a valid `multiattack` declaration and each referenced attack is supported
- **THEN** Python SHALL resolve the listed actions and counts in order
- **AND** it SHALL NOT infer attack count from the number of attack actions

#### Scenario: Bare Multiattack has no executable specification
- **WHEN** a monster has an action named `Multiattack` but no valid `multiattack` declaration
- **THEN** the resolver SHALL classify the whole batch as unsupported and leave it to the existing generate-and-validate path

#### Scenario: No Multiattack action is authored
- **WHEN** a monster has supported attack actions but no `Multiattack` action or `multiattack` declaration
- **THEN** Python SHALL resolve exactly one attack using the first supported attack action in authored order

#### Scenario: Multiattack schema data is invalid or ambiguous

- **WHEN** a present `multiattack` declaration has an invalid shape, a non-positive count, an unknown action reference, or a non-unique action-name match
- **THEN** validation SHALL reject the malformed authored monster data
- **AND** runtime SHALL route any already-loaded affected batch through whole-batch fallback

### Requirement: Supported weapon attacks SHALL follow SRD 5.2.1 attack and damage rules

Python SHALL resolve supported attack rolls, critical hits, and damage from authored attack values using the batch seed and authoritative target AC.

#### Scenario: Natural one, natural twenty, and ordinary roll
- **WHEN** a supported attack roll is a natural 1, a natural 20, or another d20 result
- **THEN** a natural 1 SHALL miss, a natural 20 SHALL hit and critically hit, and every other result SHALL hit only when attack total is at least target AC

#### Scenario: Critical damage uses the authored dice
- **WHEN** a supported attack is a critical hit
- **THEN** the attack's damage dice SHALL be rolled twice using the batch seed
- **AND** its flat damage bonus SHALL be added once

#### Scenario: Attack outcome cannot be determined from existing data
- **WHEN** a required attack modifier, damage expression, target AC, or applicable attack-state modifier cannot be resolved deterministically
- **THEN** the whole batch SHALL use the existing generate-and-validate path without partial deterministic effects

### Requirement: Damage to a PC at zero HP SHALL preserve death-save authority

Supported damage SHALL clamp PC HP at zero, preserve the existing schema-legal unconscious/dead status contract, and apply death-save changes only through the existing deterministic death-save rules.

#### Scenario: Supported damage reduces a conscious PC to zero HP
- **WHEN** a supported attack reduces a PC from positive HP to zero or fewer HP
- **THEN** the ledger and persisted character state SHALL show zero HP and unconscious status unless the existing death-save rules require dead status
- **AND** existing death-save counters SHALL NOT be reset or replaced by narration

#### Scenario: An attack would target an already unconscious PC
- **WHEN** the target-selection order reaches a PC already at zero HP or unconscious and resolving the attack would require an unmodeled advantage, critical, or death-save rule
- **THEN** the whole batch SHALL use the existing generate-and-validate path without partial deterministic effects

### Requirement: Interim morale thresholds SHALL defer only critical batches

The resolver SHALL record bloodied status without treating it as a fallback trigger, and SHALL defer whole batches at the interim near-death or leader boundaries.

#### Scenario: Bloodied-only enemy remains supported
- **WHEN** a scheduled enemy has positive HP at or below half its authoritative maximum HP at batch start
- **THEN** Python SHALL keep the batch eligible if all other mechanics are supported
- **AND** the ledger SHALL record `bloodied=true` for that enemy
- **AND** narration MAY describe the bloodied state

#### Scenario: Near-death enemy triggers fallback
- **WHEN** a scheduled enemy has positive HP at or below 25% of its authoritative maximum HP at batch start
- **THEN** Python SHALL decline the whole batch before applying deterministic effects
- **AND** the existing LLM path SHALL decide whether the enemy flees, surrenders, or continues

#### Scenario: Explicitly designated leader is down
- **WHEN** an encounter combatant has `leader=true` and that leader is dead, defeated, or at zero HP
- **THEN** Python SHALL classify the batch as a morale fallback without inferring leadership from name or challenge rating

#### Scenario: Legacy encounter has no leader marker

- **WHEN** an encounter omits the optional `leader` field
- **THEN** the resolver SHALL NOT infer a leader from a name, role, or challenge rating
- **AND** the encounter SHALL remain valid under its existing required-field contract

#### Scenario: Encounter has multiple leader markers

- **WHEN** more than one encounter combatant has `leader=true`
- **THEN** the resolver SHALL treat leader identity as ambiguous
- **AND** it SHALL defer the whole batch to the existing generate-and-validate path before applying deterministic effects

#### Scenario: Morale boundary remains interim

- **WHEN** the follow-on tactical behavior is implemented
- **THEN** intelligent self-preservation SHALL be specified by `combat-tactical-brain`
- **AND** this interim resolver SHALL NOT implement a Python morale system

#### Scenario: Spell or special action triggers fallback
- **WHEN** any scheduled enemy action requires a spell, save, condition, legendary action, reaction, or unsupported special mechanic
- **THEN** the whole batch SHALL use the existing generate-and-validate path and no deterministic ledger effects SHALL be applied
