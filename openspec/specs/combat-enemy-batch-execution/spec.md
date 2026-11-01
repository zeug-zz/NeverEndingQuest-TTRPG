# combat-enemy-batch-execution Specification

## Purpose
Defines narration, persistence, traceability, and rollback behavior for deterministic enemy batches while preserving existing combat lifecycle contracts.

## Requirements

### Requirement: Supported batches SHALL use one narration-only provider request

A supported enemy batch SHALL make one `llm.call` narration request from its completed ledger and scene context, and SHALL NOT make a combat-validation request.

#### Scenario: Supported batch narration succeeds
- **WHEN** Python resolves a supported enemy batch and narration checks pass
- **THEN** the batch SHALL make exactly one narration request and no validation request
- **AND** the accepted narration SHALL describe the ledger without proposing or applying mechanics

#### Scenario: Unsupported batch uses compatibility path
- **WHEN** Python declines any action in an enemy batch
- **THEN** the entire batch SHALL use the existing LLM generation-and-validation path unchanged

### Requirement: Narration SHALL be checked against the authoritative ledger

Python SHALL accept narration only when its actor and target names and every stated roll, hit, miss, damage, HP, and defeat claim agree with the completed ledger.

#### Scenario: Narration contains an invented hit or kill
- **WHEN** narration claims a hit, damage, or defeat absent from the ledger
- **THEN** Python SHALL reject that narration without changing the ledger or issuing another narration request

#### Scenario: Narration check fails
- **WHEN** any deterministic narration check fails
- **THEN** Python SHALL emit deterministic ledger-derived template narration
- **AND** record the bounded check-failure reason
- **AND** make no second narration or validation request

### Requirement: Provider terminal outcomes SHALL retain router authority

The narration request SHALL use the existing router's timeout, transport retry, outage, quota, refusal, and terminal-error handling without a combat-owned retry or provider policy.

#### Scenario: Router reports a terminal provider outcome
- **WHEN** narration receives a router terminal outcome
- **THEN** the combat path SHALL preserve existing terminal-error handling
- **AND** SHALL NOT convert that outcome into fabricated successful narration

### Requirement: Batch persistence SHALL preserve atomic file writes and order

The supported batch SHALL make one atomic history checkpoint before state writes, then write changed PCs before the final encounter projection.

#### Scenario: One-PC batch changes one PC and the encounter
- **WHEN** a supported one-PC batch changes that PC and enemy encounter state
- **THEN** the character file SHALL be persisted atomically before the encounter file
- **AND** each of those paths SHALL be written no more than once for the batch

#### Scenario: Multi-PC batch changes two PCs
- **WHEN** a supported batch changes two PC files and the encounter file
- **THEN** each changed character file SHALL be written atomically once before one atomic encounter write
- **AND** all other gameplay-state writes attributed to the batch SHALL remain separately countable

#### Scenario: Supported batch writes one pre-apply transcript

- **WHEN** a supported batch has accepted or templated its final narration
- **THEN** the user-turn input and final narration SHALL be persisted together in exactly one combat-history file write
- **AND** that write SHALL occur before changed PC files and the final encounter write, preserving the existing pre-apply transcript checkpoint used by resume/replay behavior
- **AND** the existing atomic JSON helper SHALL be used, with separate batch-attributed input/assistant history writes deferred or merged
- **AND** each changed PC file SHALL be persisted once before the encounter is persisted once

#### Scenario: Supported batch coalesces lifecycle state into the encounter write

- **WHEN** existing round, phase, or opening-marker logic changes encounter state during a supported batch
- **THEN** the existing in-memory lifecycle transition SHALL remain in effect
- **AND** its final encounter projection SHALL be included in the single post-character encounter write

### Requirement: G5R SHALL count physical gameplay-state writes per batch

The G5R write metric SHALL count each atomic write to a distinct gameplay or history file attributed to the batch; grouping several paths into one helper call SHALL NOT count them as one write. Trace/evidence output writes SHALL be excluded.

#### Scenario: Batch write count is reported
- **WHEN** a captured enemy batch writes character, encounter, party, or conversation-history state
- **THEN** each attributed file write SHALL contribute one to the raw batch count
- **AND** the G5R absolute target SHALL remain no more than three writes

#### Scenario: Outcome requires more than three file writes
- **WHEN** a supported batch outcome requires more than three attributed gameplay-state file writes
- **THEN** G5R SHALL report the absolute write target as FAIL
- **AND** SHALL NOT relabel a multi-file operation as one write
- **AND** with one history and one encounter write, an outcome changing two or more PC files SHALL fail the raw limit

### Requirement: Resolver activation SHALL have a tested rollback flag

Deterministic enemy resolution SHALL be controlled by a configuration flag that remains disabled until G5R acceptance and can restore the existing generate-and-validate path.

#### Scenario: Rollback flag is disabled
- **WHEN** the deterministic enemy-resolution flag is false
- **THEN** enemy batches SHALL use the existing generate-and-validate path
- **AND** no deterministic batch narration or persistence path SHALL run

#### Scenario: Gate has not passed
- **WHEN** implementation is staged before a primary-reviewed G5R PASS
- **THEN** the shipped default SHALL remain disabled

### Requirement: Existing combat lifecycle and static prompts SHALL remain unchanged

Deterministic enemy processing SHALL preserve initiative, opening enemy batch, enemy turn window, round and phase transitions, death-save cadence, PC phase, and resume-replay behavior; existing static combat prompt files SHALL remain byte-identical.

#### Scenario: Opening enemy batch is resolved
- **WHEN** the DM group wins initiative and an opening enemy batch is due
- **THEN** it SHALL use the same resolver eligibility, fallback, and persistence contracts as an `/end` batch
- **AND** existing opening-batch phase progression SHALL remain unchanged

### Requirement: Supported batches SHALL use only the scoped lifecycle transitions

For a fully supported deterministic batch, Python SHALL derive lifecycle changes only for the recognized PC-phase `/end` and DM-group opening-batch cases. Lifecycle save callbacks SHALL capture payloads in memory and SHALL NOT add writes outside the batch's single history and encounter writes. Other or inconsistent lifecycle states SHALL decline before ledger application with bounded reason `round_transition_unsupported`; the legacy path SHALL preserve model-reported `combat_round` behavior.

#### Scenario: PC-phase `/end` closes the current round

- **GIVEN** an `/end` enemy batch with `roundStartsWith` equal to `pcGroup` or omitted and no opening batch pending
- **WHEN** the batch is fully supported at authoritative round R
- **THEN** the batch SHALL derive round R+1 in code through `apply_reported_round_transition`
- **AND** the resulting manager phase, round, initiative state, and marker state SHALL match the existing transition for a response reporting R+1
- **AND** any boundary-compressed history SHALL be included in the single batch history write

#### Scenario: DM-group opening batch returns to PC phase

- **GIVEN** a fully supported opening batch with `openingEnemyBatchPending=true`, `roundStartsWith=dmGroup`, and the manager in `ENEMY_PHASE`
- **WHEN** the batch completes
- **THEN** the round SHALL remain unchanged
- **AND** the opening marker SHALL be cleared and `pc_phase_complete` SHALL be false
- **AND** the resulting manager phase and encounter marker state SHALL match `complete_opening_enemy_batch`

#### Scenario: Unsupported lifecycle state uses the legacy path

- **WHEN** a deterministic batch has `/end` with `roundStartsWith=dmGroup`, an opening marker inconsistent with manager phase, or any other lifecycle combination outside the two supported cases
- **THEN** deterministic resolution SHALL decline with `round_transition_unsupported` before applying any ledger entry
- **AND** the entire batch SHALL use the existing generate-and-validate path with model-reported `combat_round` behavior unchanged

#### Scenario: Existing prompt assets are checked
- **WHEN** the change's prompt compatibility check runs
- **THEN** all pre-existing static combat prompt files SHALL match their recorded pre-change bytes
