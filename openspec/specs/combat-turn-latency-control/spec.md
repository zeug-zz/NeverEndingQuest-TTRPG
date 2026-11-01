# combat-turn-latency-control Specification

## Purpose

Define bounded combat-turn latency behavior that reduces repeated hot-path work while preserving Python mechanical authority and equivalent 1-PC-party and multi-PC outcomes.

## Requirements

### Requirement: Combat provider calls SHALL have an effective timeout

Every combat provider request SHALL be bounded by the shared router client timeout or an existing explicit timeout; combat SHALL NOT introduce a parallel timeout policy.

#### Scenario: Combat provider site is covered

- **WHEN** any combat provider request is issued
- **THEN** it SHALL have an effective timeout
- **AND** provider retry and outage handling SHALL remain under the existing router policy

#### Scenario: Timeout coverage is missing

- **WHEN** a combat provider site has neither a router client timeout nor an explicit bound
- **THEN** the G5 implementation verification SHALL fail

### Requirement: Combat history compression SHALL follow round boundaries

The runtime SHALL compress completed-round history once at the round boundary, retain LLM compression only for the boundary round, and SHALL NOT invoke per-message or per-attempt LLM compression.

#### Scenario: A round boundary is reached

- **WHEN** combat advances to a new round
- **THEN** completed-round compression SHALL run at that boundary
- **AND** no completed message SHALL receive an additional per-message or per-attempt LLM compression

### Requirement: Stale combat rounds SHALL be trimmed deterministically

Combat rounds older than the configured retention window SHALL be reduced by deterministic truncation rather than additional LLM compression.

#### Scenario: History exceeds the retention window

- **WHEN** completed rounds older than the retention window are present
- **THEN** their retained context SHALL be produced by deterministic truncation
- **AND** the retained boundary-round compression SHALL remain available

### Requirement: Per-attempt diagnostic dumps SHALL be debug-gated

Per-attempt combat JSON dumps SHALL be written only when the debug flag is enabled; the working-directory `combat_messages_to_api.json` dump SHALL NOT be written.

#### Scenario: Debug dumps are disabled

- **WHEN** a combat attempt runs with the debug flag OFF
- **THEN** it SHALL write no per-attempt JSON dump
- **AND** it SHALL NOT create or update `combat_messages_to_api.json` in the working directory

#### Scenario: Debug dumps are enabled

- **WHEN** a combat attempt runs with the debug flag ON
- **THEN** only the existing debug-scoped diagnostic dump behavior SHALL be available
- **AND** no game-state file SHALL be substituted as a diagnostic destination

### Requirement: Validation may be skipped only for safe deterministic action sets

Combat validation SHALL be skipped only when deterministic prechecks pass and the response contains only actions classified as deterministic-mechanics-safe; every other action set SHALL use the existing LLM validation path.

#### Scenario: Safe deterministic response passes prechecks

- **WHEN** deterministic prechecks pass for a deterministic-mechanics-only response
- **THEN** the routing decision SHALL return a skip outcome with a reason
- **AND** the skip outcome SHALL be recorded in validation telemetry

#### Scenario: Non-deterministic action or failed precheck is present

- **WHEN** deterministic prechecks fail, or any action is outside the deterministic-mechanics-safe set
- **THEN** validation SHALL NOT be skipped
- **AND** the response SHALL continue through the existing LLM validation path

#### Scenario: Possession authority is required

- **WHEN** the turn requires an authoritative possession check or contains an explicit bookkeeping-correction claim
- **THEN** combat validation SHALL NOT be skipped

### Requirement: Combat validation SHALL receive authoritative phase context separate from candidate claims

The combat validator's runtime message assembly SHALL include a bounded authoritative phase block sourced only from `multi_pc_manager`/encounter state and separate from candidate claims. LLM validation SHALL remain enabled with no new skip, and static prompt files SHALL remain byte-for-byte unchanged.

#### Scenario: Enemy batch intent is present in validator context

- **WHEN** the current phase is ENEMY_PHASE, Goblin is pending, and the input is exactly `Enemies turn.`
- **THEN** the captured validator messages SHALL contain an authoritative block with current phase, round, forbidden actors, pending enemies/current turn window, `pc_phase_complete`, `opening_batch_pending`, and `full_enemy_batch_intent`
- **AND** the validator provider call SHALL still be made exactly once

#### Scenario: Candidate claims conflict with authoritative phase state

- **WHEN** a candidate claims a phase, round, actor window, or batch intent that conflicts with manager/encounter state
- **THEN** the runtime message SHALL retain the code-derived authoritative block separately from the candidate
- **AND** the candidate claim SHALL NOT replace or amend authoritative values

#### Scenario: Static prompt assets are preserved

- **WHEN** the dynamic validator phase context is added
- **THEN** no static prompt file SHALL change
- **AND** the LLM validator path SHALL remain active

### Requirement: Deterministic validation failures SHALL have a bounded retry ladder

For deterministic-failure classes, combat validation SHALL make no more than two validation attempts; this bound SHALL NOT replace or alter router-owned provider outage, quota, or transport retry behavior.

#### Scenario: Deterministic validation keeps failing

- **WHEN** a deterministic-failure class remains after two validation attempts
- **THEN** the validation ladder SHALL stop at two attempts
- **AND** the existing per-class exhaustion outcome SHALL be preserved unchanged (guard and multiple-updateEncounter rejections retain the last response with valid_response=False; combatant-integrity exhaustion skips; invalid-JSON format failures are not deterministic-failure classes and keep the existing ladder)

#### Scenario: Provider transport failure occurs

- **WHEN** a provider outage, quota, or transport failure occurs
- **THEN** the existing router retry and recovery behavior SHALL remain authoritative
- **AND** the deterministic validation-attempt cap SHALL NOT reclassify the provider failure

### Requirement: Memoized combat context SHALL be byte-identical and state-keyed

Memoized head context, initiative tracker, party-turn summary, PC prompt context, and PC-phase ledger output SHALL be byte-identical to fresh rendering for the same state key of round, phase, active PC, and encounter revision.

#### Scenario: The complete state key is unchanged

- **WHEN** a context value is requested again with the same round, phase, active PC, and encounter revision
- **THEN** the memoized output SHALL be byte-identical to the unmemoized rendering

#### Scenario: Any state-key component changes

- **WHEN** the round, phase, active PC, or encounter revision changes
- **THEN** a value from the prior key SHALL NOT be returned as current context

### Requirement: Active encounter synchronization SHALL run once per turn and write only changes

The runtime SHALL synchronize the active encounter at most once per combat turn and SHALL persist the encounter only when its authoritative state changed, using the existing atomic persistence contract.

#### Scenario: Encounter state is unchanged

- **WHEN** the turn synchronization observes no encounter-state change
- **THEN** no encounter write SHALL occur

#### Scenario: Encounter state changed during the turn

- **WHEN** authoritative encounter state changes during a turn
- **THEN** synchronization SHALL persist the changed encounter state at most once for that turn
- **AND** the existing atomic persistence behavior SHALL be preserved

### Requirement: Combat reasoning escalation SHALL use router retry tiers

When validation-failure class requires reasoning escalation, combat SHALL communicate that escalation through the router retry tier and SHALL NOT add a combat-owned provider retry or reasoning-profile path.

#### Scenario: Escalation is required

- **WHEN** the existing validation-failure class requires reasoning escalation
- **THEN** the provider request SHALL carry the corresponding router retry tier
- **AND** provider, quota, and retry behavior SHALL remain router-owned

#### Scenario: Escalation is not required

- **WHEN** no validation-failure class requires reasoning escalation
- **THEN** combat SHALL NOT request a higher retry tier

### Requirement: The NL PC-phase fast path SHALL remain a reversible canary

When enabled for eligible tabletop PC_PHASE input, the NL fast path SHALL handle supported attack, heal, magic-missile, and movement actions deterministically; a parse miss, failed application, or unavailable parser SHALL fall through to the existing LLM path.

#### Scenario: Supported action is parsed and applied

- **WHEN** an eligible PC_PHASE action is parsed and its deterministic application succeeds
- **THEN** the action SHALL complete without a provider call
- **AND** telemetry SHALL record a fast-path hit

#### Scenario: 1-PC tabletop party uses the same eligibility contract

- **WHEN** the fast-path flag is enabled for eligible PC_PHASE input in a 1-PC party
- **THEN** the same parser/application contract SHALL apply
- **AND** party size SHALL NOT add a separate activation gate

#### Scenario: Parse misses or deterministic application rejects the result

- **WHEN** parsing declines an action or deterministic application fails
- **THEN** telemetry SHALL record the miss or false-positive outcome distinctly
- **AND** the existing LLM path SHALL receive the action

#### Scenario: Parser is unavailable

- **WHEN** the fast-path parser cannot be loaded or is otherwise unavailable
- **THEN** telemetry SHALL record `unavailable` distinctly from a parse miss
- **AND** the existing LLM path SHALL receive the action

#### Scenario: Canary is rolled back

- **WHEN** `COMBAT_PC_PHASE_NL_FAST_PATH` is set to `False`
- **THEN** the NL fast path SHALL be disabled
- **AND** eligible input SHALL use the existing LLM path

### Requirement: Combat hot-path optimization SHALL preserve combat authority

The hot-path changes SHALL preserve static prompt assets, Python mechanical authority, roster and phase integrity, death-save and initiative gates, enemy-batch semantics, resume-replay protection, and atomic state persistence except for the specified call and write cadence changes. The approved dynamic validator phase block SHALL remain equivalent in matched G5 before and after captures.

#### Scenario: Equivalent 1-PC and multi-PC fixtures run

- **WHEN** the fixed 1-PC-party or multi-PC fixture executes before and after the optimization
- **THEN** its static prompt assets, dynamic authoritative validator context, and authoritative combat transitions SHALL remain equivalent
- **AND** only the specified compression, validation, synchronization, and diagnostic call/write cadence MAY differ
