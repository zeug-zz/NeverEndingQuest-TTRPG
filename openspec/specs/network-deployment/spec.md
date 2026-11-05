# network-deployment Specification

## Purpose
Defines how the NeverEndingQuest player network surface is reached and isolated:
which tunnel companion is used and how it is confined, which listeners exist, how
authenticated transport behaves through the tunnel, and what evidence proves it.

## Requirements

### Requirement: Pinned, isolated tunnel companion

The spike SHALL use upstream OpenTunnel v0.6.2, stored outside any Python
virtual environment and verified against the release `SHA256SUMS` before
execution. It SHALL run foreground (`opentunnel serve`) with a dedicated
`--profile`, project-isolated XDG directories, and PROXY protocol off, and SHALL
NOT leave a service registration or touch any other profile.

#### Scenario: Checksum mismatch stops the run
- **WHEN** the downloaded archive digest does not match `SHA256SUMS`
- **THEN** the driver MUST NOT execute the binary and MUST record a FAIL with expected and observed digests

#### Scenario: No service registration remains
- **WHEN** a spike run ends (normally or by failure)
- **THEN** no `xyz.opentunnel.*` launchd entry or `opentunnel-*.service` unit created by the run exists, no opentunnel process started by the run is alive, and the route is removed

#### Scenario: Other profiles untouched
- **WHEN** the user has an unrelated OpenTunnel profile
- **THEN** the run MUST NOT read, modify, or stop it, because all state resolves under the run's isolated XDG directories

### Requirement: Loopback-only inert fixture

The fixture SHALL listen only on `127.0.0.1:8370`, SHALL serve only static
assets and a counter/echo Socket.IO namespace, and SHALL NOT import, read, or
serve game modules, campaign files, characters, party state, or configuration
secrets. It SHALL NOT be imported by the host runtime.

#### Scenario: Non-loopback bind is refused
- **WHEN** the fixture is configured with any bind host other than `127.0.0.1`
- **THEN** it MUST refuse to start

#### Scenario: Fixture exposes no game data
- **WHEN** the fixture is scanned for imports and file reads
- **THEN** it references no repository game-state module or campaign path

### Requirement: Authenticated session over HTTPS

The fixture SHALL exchange a fixture password for a session cookie that is
`Secure`, `HttpOnly`, `SameSite=Strict`, with a random per-process secret and
bounded lifetime, and SHALL deliver no Socket.IO event before authentication.
Password comparison SHALL be constant-time. Wrong or missing credentials SHALL
be rejected without distinguishing the cause.

#### Scenario: Login accepted over the public URL
- **WHEN** a client posts the correct fixture password to the public HTTPS URL
- **THEN** the response sets a `Secure; HttpOnly; SameSite=Strict` cookie and the client can open the Socket.IO namespace

#### Scenario: Login rejected
- **WHEN** the password is wrong or absent
- **THEN** no session cookie is set and the Socket.IO connection is refused

#### Scenario: Unauthenticated socket delivers nothing
- **WHEN** a Socket.IO client connects without a valid session cookie
- **THEN** the connection is rejected and no counter or echo event is delivered

### Requirement: Explicit Host and Origin validation

The fixture SHALL accept requests and Socket.IO handshakes only when the `Host`
equals the configured expected public host (or the loopback host:port for local
tests) and, where an `Origin` is present, it equals the explicit expected origin.
It SHALL NOT trust `Forwarded` or `X-Forwarded-*` headers as identity, host, or
scheme.

#### Scenario: Spoofed Host rejected
- **WHEN** a request through the public URL carries a `Host` that is not the expected public host
- **THEN** the fixture rejects it and serves no content

#### Scenario: Spoofed Origin rejected
- **WHEN** an authenticated Socket.IO handshake carries an `Origin` other than the expected public origin
- **THEN** the handshake is refused

#### Scenario: Forwarding headers ignored
- **WHEN** a request carries `X-Forwarded-For`, `X-Forwarded-Host`, or `X-Forwarded-Proto`
- **THEN** none changes host validation, cookie attributes, or authentication outcome

### Requirement: Transport coverage through the tunnel

From the public HTTPS URL, on both macOS and Linux, the evidence SHALL show:
static asset serving, HTTPS scheme with `Secure` cookie behaviour, Socket.IO
over the WebSocket transport, Socket.IO over a polling-only transport, client
reconnect after a tunnel restart, and clean shutdown.

#### Scenario: WebSocket and polling both work
- **WHEN** an authenticated client connects once with WebSocket-only and once with polling-only transport
- **THEN** each receives the fixture counter event and the evidence records the negotiated transport

#### Scenario: Reconnect after tunnel restart
- **WHEN** the tunnel process is stopped and restarted while an authenticated client is connected
- **THEN** the client reconnects (re-authenticating if the session was not retained) without manual repair, or the evidence records the observed behaviour as a FAIL

#### Scenario: Clean shutdown
- **WHEN** the run completes
- **THEN** the route is removed, no process started by the run remains, and a request to the public URL no longer reaches the fixture

### Requirement: Evidence and gate verdict

Each platform run SHALL write redacted JSON evidence under
`tmp/router-rollout/v2-network/n0-<platform>-<run-id>/` with build SHA, platform,
OpenTunnel version and digest, and expected versus observed result per check.
The primary orchestrator SHALL decide gate N0 per platform as PASS, FAIL, or
BLOCKED; a missing platform, relay refusal, or unsolved runtime ownership SHALL
be BLOCKED and never waived.

#### Scenario: Missing Linux leg
- **WHEN** the Linux run cannot execute
- **THEN** N0 is BLOCKED with the reason recorded and the matter goes to owner plan review

#### Scenario: Driver exit code alone is insufficient
- **WHEN** the driver exits 0 but any required check is absent or failed in the evidence JSON
- **THEN** the platform verdict is not PASS

### Requirement: Single-runtime listener decision recorded

The change SHALL record a selected player-listener and runtime integration
(distinct loopback listener, separate application object, same Python process,
bounded typed in-process gateway) with rejected alternatives, and SHALL state that
the host Flask-SocketIO application stays local-only and is never tunnelled.

#### Scenario: Decision artifact exists
- **WHEN** the change is reviewed
- **THEN** `design.md` names the chosen integration, serving stack, rejected alternatives with reasons, reversibility, and dependency-addition obligations
