# Spec Delta

## Purpose

Defines the fork-owned browser client and its player-boundary assets for a coherent, least-privilege N2 gameplay experience.

## ADDED Requirements

### Requirement: Player client assets SHALL use bounded same-origin routes

The player shell and its versioned, content-hashed assets SHALL be served only by the existing player ASGI `GET /` and `GET /static/player/<asset-id>` routes. Asset IDs SHALL resolve only through a bounded manifest; responses SHALL use same-origin URLs, `nosniff`, a restrictive CSP, and cache policy appropriate to immutable hashed assets. The host Flask application SHALL NOT serve these assets.

#### Scenario: Player shell and hashed assets are served
- **WHEN** a browser requests the player shell and each asset ID named by its manifest
- **THEN** the player listener returns only those player assets with the required headers and the host Flask application serves none of them

#### Scenario: Unknown asset ID is requested
- **WHEN** a browser requests a static player asset ID absent from the bounded manifest
- **THEN** the player listener rejects it without reading an arbitrary file or falling back to a host route

### Requirement: Player asset and protocol incompatibility SHALL fail closed

The player shell and bundle SHALL identify their build and protocol versions. HTTP snapshot requests and Socket.IO handshakes SHALL identify the client build and protocol; the listener SHALL reject mismatches before protected data or gameplay work and provide a clear diagnostic. A failed asset preflight SHALL NOT advertise listener readiness or fall back to the host UI.

#### Scenario: Client build or protocol version is incompatible
- **WHEN** a browser presents a client build or protocol version not supported by the listener
- **THEN** the listener rejects the snapshot or socket connection with an explicit compatibility error and the client displays a resynchronization or reload message without submitting gameplay input

#### Scenario: Build manifest is missing or corrupt
- **WHEN** the explicit player listener is started without a valid manifest, a complete asset set, or matching asset digests
- **THEN** it fails closed with a clear diagnostic, opens no ready player surface, and does not serve the facilitator UI

### Requirement: Player UI SHALL present a coherent safe gameplay projection

The client SHALL render the ordered shared transcript, shared active PC, approved character sheets and portraits, relevant initiative and combat state, and bounded busy state from server projections. Browser state SHALL remain a cache; untrusted narrative and player text SHALL render without executable raw HTML.

#### Scenario: One-PC party is presented
- **WHEN** an authenticated client hydrates a 1-PC snapshot and receives subsequent player events
- **THEN** it shows the single approved sheet, shared active PC, transcript, relevant combat state, and busy state without requiring a multi-PC-only model

#### Scenario: Four-PC party stays coherent across clients
- **WHEN** the host and at least two authenticated clients use a 4-PC party while transcript, active PC, sheets, initiative, combat, or busy state changes
- **THEN** all clients converge on the same server-projected state and ordered transcript without exposing unprojected or host-only fields

#### Scenario: Narrative contains HTML or an unsafe URL
- **WHEN** projected narrative or player text contains raw HTML or an unsafe URL scheme
- **THEN** the player display treats it as non-executable text and does not load the unsafe destination

### Requirement: Player selections and input SHALL preserve N1 race and receipt semantics

The client SHALL use only the N1-allowlisted player routes and events, including `player.snapshot.request`, `player.active_pc.select`, and `player.input.submit`. It SHALL carry the current protocol and active-PC revision, display typed accepted, duplicate, busy, stale, rejected, and uncertain outcomes, and SHALL never retarget input or automatically replay an uncertain submission after an instance change.

#### Scenario: Another client changes the active PC before input admission
- **WHEN** a client submits input with an obsolete active-PC revision or a no-longer-active character
- **THEN** the server returns a stale receipt, the client refreshes authoritative state and surfaces the stale result, and no PC receives the input

#### Scenario: Input is busy, rejected, or uncertain
- **WHEN** the server returns a busy, rejected, or uncertain receipt
- **THEN** the client visibly identifies that outcome and does not present it as accepted or automatically resubmit it

#### Scenario: Client retries or reconnects after an instance change
- **WHEN** a client retries an existing request ID or reconnects with a new server instance
- **THEN** it displays the original or uncertain result as applicable, resynchronizes from an authoritative snapshot, and never causes duplicate enqueue or LLM work

### Requirement: Player bundle SHALL exclude host-only capabilities

The production player bundle SHALL exclude toolkit, settings, lifecycle, party-editing, and debug code and entry points. A built-output content/dependency test SHALL fail when a forbidden host-only module or capability marker is present.

#### Scenario: Built bundle contains a host-only capability
- **WHEN** the bundle-content test scans the generated player output
- **THEN** it rejects any host-only module or capability marker and the bundle is not accepted for serving

### Requirement: Local host startup SHALL be independent of player assets

Ordinary host startup and local facilitator operation SHALL NOT require Node.js, a frontend package installation, or a valid player bundle. Missing or broken player assets SHALL affect only an explicitly started player listener.

#### Scenario: Host starts with sharing disabled and no client build
- **WHEN** the host starts with the player listener disabled and the player bundle missing or broken
- **THEN** no player listener opens and ordinary local facilitator operation remains available without invoking Node.js

#### Scenario: Opted-in listener cannot load its client build
- **WHEN** the development/test listener is explicitly requested but asset preflight fails
- **THEN** the listener remains not-ready, reports the failure, and leaves local facilitator operation available

### Requirement: N2 listener startup SHALL be explicit and loopback-only

N2 development and gate startup SHALL require an explicit off-by-default opt-in and the existing facilitator-supplied scrypt verifier, and SHALL bind only to `127.0.0.1:8370`. This temporary opt-in SHALL be replaced by N3 facilitator sharing controls.

#### Scenario: Development opt-in is absent
- **WHEN** ordinary host startup has no N2 development/test opt-in
- **THEN** the player listener remains stopped

#### Scenario: Development opt-in is valid
- **WHEN** an authorized facilitator enables the N2 development/test opt-in with a valid verifier and client bundle
- **THEN** the listener starts only on loopback port 8370 and still exposes only player capabilities
