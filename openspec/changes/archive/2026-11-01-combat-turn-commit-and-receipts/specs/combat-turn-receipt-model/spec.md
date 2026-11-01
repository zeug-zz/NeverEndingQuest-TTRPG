# Spec Delta

## Purpose

Defines durable identity and receipt semantics for a combat turn so state mutations can be committed and safely recognized after process restart.

## ADDED Requirements

### Requirement: Receipt SHALL Reserve an Optional Position-Delta Slot

The per-turn receipt and committed final encounter snapshot SHALL allow an optional, additive `position_deltas` slot. Missing is equivalent to empty. Current code SHALL NOT write or read position deltas.

#### Scenario: A turn commits without spatial data
- **WHEN** a turn commits with no spatial data
- **THEN** the receipt and committed snapshot SHALL be valid with the slot absent or empty
- **AND** no current code path SHALL write or read position deltas

### Requirement: Combat Turn Receipts SHALL Use the Versioned Exact Schema

The encounter SHALL retain an append-only `turn_receipts` array. Each receipt MUST contain exactly `schema_version` (integer `1`), `turn_id` (UUID string), `applied_id` (`sha256:` plus 64 lowercase hexadecimal characters), `encounter_id` (non-empty string), `combat_round` (positive integer), and `commit_timestamp` (UTC RFC3339 timestamp ending in `Z`).

#### Scenario: A committed turn has one durable receipt
- **WHEN** the encounter-last commit for a turn succeeds
- **THEN** the encounter SHALL contain exactly one receipt for that turn with all required fields and valid types
- **AND** `commit_timestamp` SHALL identify the durable encounter-write time in UTC

### Requirement: Applied IDs SHALL Be Stable Across Restart

Each accepted input SHALL receive a `turn_id` persisted with its input-history record before any mechanical state write. `applied_id` SHALL equal `sha256:` plus lowercase SHA-256 hex of UTF-8 `neq.combat.turn.applied-id.v1\0{encounter_id}\0{turn_id}`; retries SHALL reuse the persisted `turn_id`, and identity metadata SHALL NOT enter model-visible prompt bytes.

#### Scenario: The same accepted turn resumes after restart
- **GIVEN** an accepted input-history record has a persisted `turn_id`
- **WHEN** that turn resumes after a process restart
- **THEN** the runtime SHALL derive the same `applied_id` from the same encounter and `turn_id`
- **AND** a distinct accepted input SHALL receive a distinct `turn_id`, even if its text is identical

### Requirement: Turn Effects SHALL Commit Character-First and Encounter-Last

The runtime SHALL atomically persist each changed character before atomically persisting the final encounter projection with the turn receipt. Each changed character record SHALL store `last_combat_applied_id` in the same write as its turn effects; an existing matching receipt or character marker SHALL prevent reapplication of that turn's effects.

#### Scenario: Restart follows a partial character commit
- **GIVEN** one or more character files contain the turn's `last_combat_applied_id` and the encounter has no matching receipt
- **WHEN** the same turn resumes
- **THEN** the runtime SHALL skip effects already marked on characters
- **AND** it SHALL persist remaining character effects and the encounter receipt once

#### Scenario: A completed turn is replayed
- **GIVEN** the encounter already contains a receipt with the turn's `applied_id`
- **WHEN** the same turn is replayed
- **THEN** the runtime SHALL apply no character, resource, enemy, or reward effect again
- **AND** it SHALL NOT append a duplicate receipt

### Requirement: Pending Turn Commits SHALL Be Recoverable From a History Manifest

Before the first changed-character write, the runtime SHALL persist a bounded, private commit manifest (`schema_version: 1`) on the turn's history record. It SHALL preserve the staged data needed to complete the accepted turn after restart and SHALL be omitted from provider-bound projections so prompt bytes remain unchanged.

#### Scenario: The manifest preserves the complete bounded commit payload
- **GIVEN** either commit path has staged a turn
- **WHEN** the pre-commit history record is written
- **THEN** its version-1 manifest SHALL contain `turn_id`, `applied_id`, `encounter_id`, and `path` (`normal` or `enemy_batch`)
- **AND** it SHALL contain changed-character effect payloads exactly as `commit_combat_turn` applies them, ordered by canonical identity
- **AND** it SHALL contain the final encounter projection or staged operations, including committed `combat_round`, phase markers, and receipt fields; staged reward effects; and success narration text/payload
- **AND** bounds SHALL match the normalized per-turn structures admitted by the commit coordinator, with invalid or oversized values rejected rather than truncated
- **AND** manifest metadata SHALL be stripped from every provider-bound projection through the existing allowlist projection, leaving prompt bytes unchanged

#### Scenario: Existing history writes carry the manifest without adding a write
- **GIVEN** a normal or enemy-batch turn has been staged
- **WHEN** its pre-commit history record is persisted
- **THEN** the enemy-batch path SHALL use the existing `persist_history` write
- **AND** the normal path SHALL move its existing assistant-response history save to immediately after staging and before the first character write
- **AND** the G5T raw write budget SHALL remain history + encounter + one write per changed character
- **AND** the receipt's durable-write timestamp SHALL be resolved at the encounter-write boundary

### Requirement: Bootstrap SHALL Complete Pending Manifests From Stored Data

During combat bootstrap / `start_game`, the runtime SHALL complete the newest history manifest whose `applied_id` has no matching encounter receipt using stored data only, without a provider call, re-planning, or regeneration.

#### Scenario: Bootstrap completes a pending turn from its stored manifest
- **GIVEN** history contains a valid pending manifest and the encounter has no receipt for its `applied_id`
- **AND** zero or more changed characters already contain that `last_combat_applied_id`
- **WHEN** combat resumes through `start_game` after a process restart
- **THEN** the runtime SHALL use the original `turn_id` and manifest without a provider call, re-planning, or regeneration
- **AND** it SHALL skip marked characters, write only missing character effects, and commit the encounter projection and receipt once
- **AND** after synchronization it SHALL publish the stored narration text/payload once with the same `applied_id` before normal resume flow

#### Scenario: Bootstrap treats a manifest with a matching receipt as complete
- **GIVEN** history contains a manifest whose `applied_id` already has an encounter receipt
- **WHEN** combat bootstrap inspects pending commits
- **THEN** it SHALL apply no character, reward, or encounter effect again
- **AND** it SHALL NOT require republication beyond the existing resume flow

### Requirement: Invalid Pending Manifests SHALL Fail Closed

A corrupt, invalid, unsupported, or out-of-bounds pending manifest SHALL fail bootstrap with an explicit error before any recovery write; the runtime SHALL NOT guess or regenerate missing payloads.

#### Scenario: Bootstrap rejects an invalid pending manifest without guessing
- **GIVEN** history contains a pending manifest that is corrupt, unsupported, or outside its bounds
- **WHEN** combat bootstrap attempts recovery
- **THEN** it SHALL fail with an explicit error before any recovery write
- **AND** it SHALL NOT make a provider call, re-plan, regenerate, or partially guess the missing effects

### Requirement: Success Publication SHALL Follow Durable Commit and Phase Synchronization

The runtime SHALL publish turn success or narration only after the encounter write containing the receipt succeeds and post-commit phase synchronization completes. Publication SHALL remain internally associated with that committed turn without changing the existing external event payload; a failed commit SHALL publish no success.

#### Scenario: Commit fails before receipt durability
- **GIVEN** any character or encounter commit write fails
- **WHEN** the runtime handles the failed turn
- **THEN** it SHALL NOT publish success or narration as a completed turn
- **AND** it SHALL retain the turn identity needed for restart recovery

#### Scenario: Commit and phase synchronization succeed
- **GIVEN** the encounter receipt and final phase snapshot are durable
- **WHEN** post-commit phase synchronization completes
- **THEN** success publication SHALL occur only after the durable receipt exists
- **AND** the existing external event payload SHALL remain unchanged

### Requirement: The Next Turn SHALL Wait for Commit and Phase Completion

The runtime SHALL NOT begin processing a subsequent combat turn until the current turn's receipt is durable and its post-commit phase synchronization is complete.

#### Scenario: A subsequent input arrives while the current turn is incomplete
- **GIVEN** the current turn has not completed its encounter commit or phase synchronization
- **WHEN** another combat input becomes available
- **THEN** the runtime SHALL defer processing it until the current turn completes
- **AND** the current turn's `applied_id` SHALL remain the active recovery identity

### Requirement: Combat Round Advancement SHALL Be Code-Owned

Python combat-manager logic SHALL derive and persist the authoritative `combat_round` from legal turn and phase transitions. Model-reported round values SHALL NOT advance, decrement, or skip the code-owned counter.

#### Scenario: A response proposes an invalid round change
- **GIVEN** a response reports a backward round, a leap, or a round unsupported by the current phase markers
- **WHEN** the turn projection is prepared for commit
- **THEN** Python SHALL retain or derive the legal round from authoritative combat state
- **AND** the committed receipt and encounter SHALL agree on that round
