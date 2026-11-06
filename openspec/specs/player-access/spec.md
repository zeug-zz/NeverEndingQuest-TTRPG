# player-access Specification

## Purpose
Defines the isolated, authenticated, and resource-bounded loopback boundary through which invited players may reach the tabletop runtime without gaining host authority.

## Requirements

### Requirement: The player listener SHALL be isolated and loopback-only

The N1 player surface SHALL use a separate ASGI application bound only to `127.0.0.1:8370` in the same Python process as the authoritative tabletop runtime. It SHALL NOT mount, proxy, wrap, or share handlers with the host Flask-SocketIO application, start a second runtime, or write canonical state directly.

#### Scenario: Player sharing is disabled
- **WHEN** the ordinary host application starts with player sharing disabled
- **THEN** no player listener is opened and the existing local host operations remain available with their existing behavior

#### Scenario: The N1 listener is explicitly started
- **WHEN** an N1 test explicitly starts the player listener
- **THEN** it binds only to `127.0.0.1:8370` in the existing process and reaches the existing runtime only through typed gateway commands and server-built projections
- **AND** the host Flask-SocketIO listener remains local-only and is never tunneled or exposed through the player application

### Requirement: Player login SHALL require an authenticated session

Player access SHALL require a non-empty facilitator-set shared credential verified with a password hash and constant-time comparison. The listener SHALL authenticate before returning snapshots or private media and before accepting or delivering player Socket.IO events. An unset credential SHALL fail closed.

#### Scenario: Missing or incorrect credential
- **WHEN** a client submits a missing or incorrect credential
- **THEN** login is rejected without distinguishing which condition failed, no session cookie is issued, and no gameplay payload or Socket.IO event is delivered

#### Scenario: Correct credential
- **WHEN** a client submits the configured credential through the player login route
- **THEN** the listener issues a host-only `Secure`, `HttpOnly`, `SameSite=Strict` session cookie and grants only the player capability set

#### Scenario: Unauthenticated client loads the login shell
- **WHEN** an unauthenticated client requests `GET /` and an exact allowlisted player-shell asset
- **THEN** it receives only the non-cacheable login shell and its public assets, with no session, gameplay, host, or administrative data
- **AND** the shell provides a one-use pre-login CSRF nonce paired with a short-lived host-only cookie

### Requirement: Player sessions SHALL expire and be revocable

Session signing SHALL use a cryptographically random per-listener secret and bounded expiry, not the host Flask secret. Logout SHALL revoke its session; stopping the player listener SHALL invalidate all sessions and disconnect player sockets; a process restart SHALL not restore revoked sessions.

#### Scenario: Session expires
- **WHEN** a client presents a correctly signed session after its expiry
- **THEN** the request and Socket.IO event are rejected before any protected data or command is processed

#### Scenario: Session is revoked
- **WHEN** a player logs out or the listener is stopped
- **THEN** the relevant live session is invalidated immediately and its connected socket cannot receive further player events or submit commands

#### Scenario: Process restarts
- **WHEN** a client presents a cookie minted by the previous player-listener process
- **THEN** the new listener rejects it and requires a new login

### Requirement: Player requests SHALL validate Host, Origin, and CSRF

The player boundary SHALL compare `Host` to an explicit allowlist and validate `Origin` for Socket.IO handshakes and state-changing requests. State-changing HTTP requests SHALL also carry same-origin CSRF proof. `Forwarded` and `X-Forwarded-*` headers SHALL NOT establish identity, host, origin, scheme, or client address.

#### Scenario: Host or Origin is not allowed
- **WHEN** an HTTP request or Socket.IO handshake presents a Host or required Origin outside the configured allowlist
- **THEN** the boundary rejects it before routing, authentication state changes, or gameplay data delivery

#### Scenario: Forwarding headers are spoofed
- **WHEN** a request contains attacker-controlled forwarding headers that conflict with its Host or Origin
- **THEN** the decision and cookie policy are unchanged from the raw Host and Origin values

#### Scenario: Cross-origin mutation is attempted
- **WHEN** a browser submits a login or other state-changing HTTP request without valid same-origin CSRF proof
- **THEN** the request is rejected without changing session, party, or gameplay state

### Requirement: Player resource use SHALL be bounded

The player boundary SHALL enforce finite configured limits for login attempts, concurrent player connections, request and event sizes, per-session input frequency, pending gameplay commands, snapshots, replay, and expensive reads. It SHALL reject over-limit work before allocating unbounded memory or starting gameplay/provider work.

#### Scenario: A request or event exceeds a configured limit
- **WHEN** a client submits a body, event, or gameplay input above its configured byte limit
- **THEN** the boundary rejects it before parsing, projection work, or queue insertion

#### Scenario: A connection, rate, or queue limit is reached
- **WHEN** a client would exceed a configured connection, attempt-rate, input-rate, expensive-read, or pending-command limit
- **THEN** the request receives a bounded rejection and no unbounded connection, queue entry, or gameplay work is created

#### Scenario: Snapshot or replay would exceed its bound
- **WHEN** the requested snapshot or replay cannot fit its configured count and byte limits
- **THEN** the server returns a bounded fresh snapshot or an explicit resynchronization result without sending an unbounded payload
