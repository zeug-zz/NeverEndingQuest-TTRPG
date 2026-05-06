# tt-combat-deterministic-command-replay-guard Specification

## Purpose
TBD - created by archiving change combat-phase-replay-stabilization. Update Purpose after archive.
## Requirements
### Requirement: Deterministic combat command results SHALL be marked already applied

Python-applied fast-lane combat command results SHALL be recorded in combat history with an explicit `[ALREADY_APPLIED]` marker and committed-state wording.

#### Scenario: Damage command reports committed result

- **WHEN** a player uses `/dmg` and Python applies enemy damage deterministically
- **THEN** the combat history message SHALL include `[ALREADY_APPLIED]`
- **AND** it SHALL report `Result HP` for the target
- **AND** it SHALL NOT be worded as an unresolved instruction for the LLM to apply damage

### Requirement: LLM responses SHALL NOT duplicate already-applied mechanics

Combat generation and validation SHALL prohibit mechanical ops that re-apply the same HP, hit, miss, ammo, or status result described in an `[ALREADY_APPLIED]` deterministic command result.

#### Scenario: Duplicate enemy damage after already-applied damage is rejected

- **GIVEN** combat history contains `[ALREADY_APPLIED] Blairen dealt 10 damage ... to Elite Bandit Bodyguard. Result HP: 8/18`
- **WHEN** the next combat response emits `updateEncounter.ops` applying another `hp_delta: -10` to `Elite Bandit Bodyguard` without a new damage source
- **THEN** deterministic validation SHALL reject the duplicate mechanical update

#### Scenario: Separate new damage source remains valid

- **GIVEN** combat history contains an `[ALREADY_APPLIED]` damage result for one attack
- **WHEN** a later response clearly describes a separate new damage source and emits corresponding ops
- **THEN** validation SHALL NOT reject solely due to the earlier already-applied marker

### Requirement: Existing resume replay protection SHALL remain independent

Active-turn already-applied replay protection SHALL NOT remove or weaken existing encounter resume replay guards.

#### Scenario: Resume replay tests still pass

- **WHEN** existing combat resume replay regression tests run
- **THEN** already-applied active-turn replay protection SHALL NOT change expected resume idempotency behavior

