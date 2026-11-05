# Spec Delta

## Purpose

Defines the complete player-visible operation set and the least-privilege data, media, and display projections available through the player boundary.

## ADDED Requirements

### Requirement: Player routes and events SHALL use a positive allowlist

The player application SHALL expose only `GET /`, `GET /static/player/<asset-id>`, `POST /api/player/login`, `POST /api/player/logout`, `GET /api/player/snapshot`, and `GET /api/player/media/<media-id>`. Its `/player` namespace SHALL accept only `player.snapshot.request`, `player.active_pc.select`, and `player.input.submit`, and emit only `player.snapshot`, `player.event`, `player.input.receipt`, and `player.error`. Unknown paths, methods, namespaces, and events SHALL be denied.

#### Scenario: An unlisted player operation is requested
- **WHEN** a client requests an unlisted path or method, connects to an unlisted namespace, or emits an unlisted event
- **THEN** the player application rejects the operation without invoking a host handler or returning host payloads

#### Scenario: The public player shell is requested without a session
- **WHEN** an unauthenticated client requests `GET /` or an exact allowlisted player-shell asset
- **THEN** it receives only the non-cacheable login shell and public assets, with no gameplay, host, or administrative data
- **AND** the shell is not the facilitator interface

#### Scenario: Host route and event inventory is checked
- **WHEN** the route/event inventory test enumerates the current host HTTP routes and Socket.IO handlers and the player application's registrations
- **THEN** every host surface is explicitly classified, the player registrations equal the positive allowlist, and an unclassified or newly exposed host operation fails the test

### Requirement: Authenticated players SHALL be denied host capabilities

Authentication SHALL grant only the player capability set. Player sessions SHALL NOT invoke party editing, character creation, toolkit, debug, settings, model, save/load/reset, update, filesystem, lifecycle, shutdown, or arbitrary action-dispatch operations, including through multiplexed or unrecognized payloads.

#### Scenario: Authenticated player attempts a host operation
- **WHEN** an authenticated player submits a host-only HTTP path, Socket.IO event, or multiplexed host action
- **THEN** the operation is rejected and no host state, filesystem, process, model, or party-editing action occurs

#### Scenario: Host-only emissions are produced
- **WHEN** the host application emits debug, cost, update, toolkit, save, plot, storage, or other host-only data
- **THEN** no player socket receives that emission

### Requirement: Gameplay data SHALL be projected by the server

Player snapshots and events SHALL be constructed from canonical state owners using explicit field allowlists. They MAY include the shared transcript, active PC, approved character-sheet fields, relevant initiative/combat state, safe media references, and bounded busy state; they SHALL NOT expose raw campaign/character/party JSON, hidden plot or GM-only notes, configuration, filesystem paths, debug output, model settings, or usage/cost data.

#### Scenario: One-PC party is projected
- **WHEN** the server builds a player snapshot for a 1-PC party
- **THEN** the snapshot contains the approved PC and shared gameplay projections without requiring a multi-PC-only state model or exposing host-only fields

#### Scenario: Four-PC party is projected
- **WHEN** the server builds a player snapshot for a 4-PC party
- **THEN** all four approved PC projections and current shared gameplay state are present, and no host-only or unprojected canonical fields are present

#### Scenario: Privileged fields exist in canonical state
- **WHEN** canonical files contain private notes, hidden plot data, storage data, host diagnostics, or unrelated fields
- **THEN** those fields are absent from every player snapshot and player event

### Requirement: Player media and display content SHALL be safe

Player media SHALL be addressed by bounded identifiers resolved by the server beneath approved media roots, never by client-supplied filesystem paths. Display text SHALL be represented as text or constrained Markdown with raw-HTML rendering disabled; unsafe URL schemes and unapproved media types SHALL be rejected.

#### Scenario: Media identifier is invalid or escapes its root
- **WHEN** a player requests an unknown media identifier or an identifier that resolves outside an approved root
- **THEN** the request is rejected without opening or disclosing any outside file or filesystem path

#### Scenario: Narrative contains HTML or an unsafe URL
- **WHEN** a projected narration or player-authored string contains HTML markup or an unsafe URL scheme
- **THEN** it is delivered only as non-executable text or rejected, and the player display contract does not interpret raw HTML

#### Scenario: Safe approved media is requested
- **WHEN** an authenticated player requests an approved media identifier
- **THEN** only the corresponding bounded media object is returned with an approved media type and no directory or source path is disclosed
