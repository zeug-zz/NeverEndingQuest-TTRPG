# Spec Delta

## Purpose

Defines the typed, ordered, bounded synchronization contract between authenticated player clients and the single authoritative tabletop runtime, including safe input acknowledgment and reconnect behavior.

## ADDED Requirements

### Requirement: Player snapshots and events SHALL use a versioned typed envelope

Every player snapshot, event, command, and receipt SHALL use an explicit schema version and validated fields. Snapshots SHALL identify the server instance, session epoch, snapshot revision, and event cursor, and SHALL contain only bounded player projections for transcript, active PC, approved sheets, relevant combat, safe media references, and busy state.

#### Scenario: A supported client requests a snapshot
- **WHEN** an authenticated client requests a snapshot using the supported protocol version
- **THEN** the server returns a schema-valid bounded snapshot with its server-instance, session-epoch, revision, and cursor identities

#### Scenario: A client submits an unsupported or malformed schema
- **WHEN** a player sends an unsupported protocol version, unknown field, invalid type, or out-of-bounds value
- **THEN** the command is rejected before runtime queue insertion or state mutation

### Requirement: Player events SHALL be ordered and reconnect SHALL be bounded

The server SHALL assign monotonically increasing event identifiers and define a snapshot/event boundary. Reconnect SHALL replay only a contiguous retained range from the same server instance and session epoch; otherwise the server SHALL require a fresh authoritative snapshot. Replay retention and payload size SHALL be finite.

#### Scenario: A client reconnects with a valid retained cursor
- **WHEN** a client reconnects with the current server instance, session epoch, and a cursor whose complete range remains retained
- **THEN** the server sends the missing ordered events once, with identifiers that allow duplicate suppression

#### Scenario: A cursor is stale, has a gap, or belongs to another instance
- **WHEN** a client reconnects with a missing, non-contiguous, expired, or different-instance cursor
- **THEN** the server sends an authoritative fresh snapshot and does not replay an incomplete range

#### Scenario: Events occur during snapshot hydration
- **WHEN** a player-visible event is published while a snapshot is being built or delivered
- **THEN** the snapshot cursor and replay boundary ensure the client receives that event or its state in the snapshot without a missed or double-applied mutation

### Requirement: Player input SHALL receive a typed idempotent receipt

Each input SHALL include a bounded request ID, server-instance and session-epoch identity, explicit character name, active-PC revision, and validated text. A receipt SHALL distinguish accepted/queued, duplicate, busy, stale, rejected, and uncertain outcomes. A repeated request ID with the same payload SHALL NOT enqueue again; reuse with a different payload SHALL be rejected. Receipts confirm queue admission only, not mechanical completion or exactly-once execution.

#### Scenario: A valid input is accepted and retried
- **WHEN** an authenticated player submits a valid input and retries the same request ID with the same payload in the same server instance
- **THEN** the server returns the original receipt and inserts the input into the runtime queue no more than once

#### Scenario: A request ID is reused with changed content
- **WHEN** a player reuses a retained request ID with a different character or input text
- **THEN** the server rejects the conflicting request and leaves the queue and game state unchanged

#### Scenario: The server restarts after an uncertain submission
- **WHEN** a client reconnects after the server instance changes and cannot determine whether its previous input was processed
- **THEN** the server marks that submission uncertain, requires resynchronization or user confirmation, and never automatically replays it

### Requirement: Active-PC selection SHALL be revisioned and race-safe

The shared active PC SHALL have a server-owned revision synchronized with host and player selections. Every input SHALL name an exact current party member and the revision it observed; the gateway SHALL reject stale revision or character context rather than substituting another client's active PC. The selection model SHALL remain shared and SHALL NOT add per-player PC ownership or party-size-specific state.

#### Scenario: A client changes the shared active PC
- **WHEN** an authorized player selects a current party member using the current active-PC revision
- **THEN** the canonical party state is updated through its approved writer, the active-PC revision advances, and the new selection is published to host and player views

#### Scenario: Another client switches PC before input is accepted
- **WHEN** an input arrives with a stale active-PC revision or a character that is no longer the active selection
- **THEN** the server returns a stale-context receipt and enqueues no input for any PC

#### Scenario: A party member is not in the current party
- **WHEN** a client submits a selection or input naming a character absent from canonical `partyMembers`
- **THEN** the request is rejected without changing the active PC or entering the game loop

### Requirement: Player commands SHALL enter the existing validated runtime

An accepted player input SHALL enter the existing game-input and validation flow through a typed in-process gateway. The player listener SHALL NOT invoke mechanics, narration, arbitrary action dispatch, persistence, or a parallel runtime directly.

#### Scenario: A player submits a valid gameplay command
- **WHEN** the gateway accepts a player command after session, schema, rate, queue, party, and active-PC validation
- **THEN** it submits exactly one explicitly character-bound input to the existing authoritative game loop and Python retains all subsequent validation and state mutation authority

#### Scenario: The runtime is busy or its bounded queue is full
- **WHEN** a command cannot be safely admitted because the game is busy or the configured queue is full
- **THEN** the server returns a busy or rejected receipt and does not start parallel gameplay or provider work
