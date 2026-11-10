# Spec Delta

## ADDED Requirements

### Requirement: Production companion SHALL use a pinned install-relative executable

Production sharing SHALL use upstream OpenTunnel v0.6.2 only at the proposed install-relative path `runtime/opentunnel/v0.6.2/<asset-stem>/opentunnel`. The resolver SHALL reject unsupported, absent, or misplaced binaries and SHALL NOT search `PATH`, download, or install. A later packaging change supplies the verified binary.

#### Scenario: Production resolver refuses an absent or misplaced companion
- **WHEN** the binary is absent, unsupported for the approved platform, outside the resolved installation root, or inside `.venv` or `venv`
- **THEN** Start sharing fails before process execution with a bounded diagnostic and does not download, install, or search `PATH`

### Requirement: Production profile state SHALL be private and isolated

Production sharing SHALL use a dedicated NEQ profile and per-profile XDG directories in private user state. Tunnel private keys SHALL remain in that profile state; the facilitator's player credential verifier SHALL use approved OS-specific private storage. Production state SHALL NOT read, modify, or stop unrelated profiles or write credentials, keys, cookies, or invitations into the repository.

#### Scenario: Production profile state is private
- **WHEN** the production profile is created or opened
- **THEN** its XDG state has private permissions, unrelated profiles and repository/campaign files remain untouched, and the credential verifier comes from the approved private store

### Requirement: Production identity setup SHALL leave no background service

Production identity setup SHALL stop and reap any temporary helper before readiness. The companion SHALL run only as the owned foreground `serve` process with a dedicated profile and route to `127.0.0.1:8370`; it SHALL NOT leave a service registration or background daemon.

#### Scenario: Production identity setup cannot leave a background service
- **WHEN** production sharing creates or verifies the dedicated OpenTunnel identity
- **THEN** every temporary helper is stopped and reaped before readiness and only the owned foreground process can expose the player listener

### Requirement: Sharing readiness SHALL fail closed

The sharing controller SHALL report `ready` and return an invitation only after the game is available, player assets are verified and served, the authenticated player listener is healthy on loopback, N1 authentication is configured, and the owned tunnel route passes its health check.

#### Scenario: A startup dependency is not ready
- **WHEN** any readiness prerequisite is missing or fails during startup
- **THEN** no invitation is returned, the public route is not advertised, the state is failed or degraded, and local facilitator play remains available

#### Scenario: The full stack becomes ready
- **WHEN** every readiness prerequisite passes for the same owned sharing generation
- **THEN** the controller reports `ready` and makes the HTTPS invitation available only to the local facilitator surface

### Requirement: Sharing supervision SHALL remain explicit and bounded

The companion SHALL run as a foreground, process-supervised child with no unattended start-at-login service. Relay recovery SHALL use a finite reconnect/backoff budget; a relay or companion failure SHALL NOT stop local gameplay or automatically resubmit gameplay input.

#### Scenario: Relay connectivity is lost
- **WHEN** the active relay becomes unhealthy
- **THEN** sharing reports degraded status, performs only the configured bounded reconnect attempts, keeps local gameplay available, and does not replay queued or uncertain player input

#### Scenario: Reconnect recovers the tunnel
- **WHEN** a bounded reconnect restores the relay
- **THEN** the controller rechecks the complete readiness predicate before restoring `ready`, and clients must resynchronize through the existing player protocol without automatic input resubmission

#### Scenario: Reconnect budget is exhausted
- **WHEN** the configured reconnect budget is exhausted
- **THEN** sharing reports a clear failed/degraded diagnostic, withdraws the invitation, and exposes no unauthenticated replacement service

### Requirement: Sharing state transitions SHALL be serialized

Start, stop, rotation, and recovery operations SHALL be linearized per NEQ profile so concurrent requests cannot create multiple listeners, tunnel processes, or routes. A stop accepted during startup SHALL cancel that startup generation and prevent it from later becoming ready.

#### Scenario: Sharing is started twice
- **WHEN** a second Start sharing request arrives while the same profile is starting or ready
- **THEN** it creates no additional process, listener, identity, or route and returns the current bounded state

#### Scenario: Stop races with startup
- **WHEN** Stop sharing is accepted before startup reaches ready
- **THEN** the startup generation is cancelled, its owned resources are cleaned up, and no invitation or later ready state is published

#### Scenario: Start and stop requests overlap
- **WHEN** facilitator start and stop requests overlap for one profile
- **THEN** they complete in one serialized order, the final state matches the last accepted operation, and no unowned process or route remains

### Requirement: Sharing cleanup SHALL affect only NEQ-owned resources

Stop, normal exit, launcher restart, failed startup, and crash recovery SHALL stop only processes and routes proven to belong to the dedicated NEQ profile. Cleanup SHALL remove the active route and invalidate public reachability; uncertain ownership SHALL fail closed without signaling an unrelated process or changing another profile.

#### Scenario: Sharing stops normally
- **WHEN** the facilitator stops sharing
- **THEN** the owned foreground companion is stopped and reaped, the active route is removed, the player listener and its sessions are stopped, and the public invitation no longer reaches the player service

#### Scenario: Launcher restarts after sharing was active
- **WHEN** a new host process starts after a prior host process exited or crashed
- **THEN** sharing remains off until explicit facilitator consent, and startup reconciles only an orphan whose process and route ownership match the dedicated NEQ profile

#### Scenario: An orphan's ownership cannot be proven
- **WHEN** a stale PID or route cannot be positively matched to the NEQ-owned profile and executable
- **THEN** the controller does not signal or remove it, sharing remains unavailable, and a bounded diagnostic requests facilitator action

### Requirement: Sharing diagnostics SHALL exclude credentials

Sharing status and diagnostics SHALL use bounded reason codes and safe lifecycle metadata. They SHALL NOT include passwords, verifiers, session cookies, private keys, raw invitation URLs, or unbounded companion output in logs, persisted artifacts, or evidence.

#### Scenario: A diagnostic contains secret-bearing input
- **WHEN** a process, status response, or error contains a credential or invitation value
- **THEN** the value is redacted before logging or evidence persistence, and the diagnostic retains only its bounded reason and lifecycle state

### Requirement: N3 lifecycle evidence SHALL be primary-owned

The later N3 lifecycle gate SHALL be run and judged by the primary orchestrator only after focused provider-free tests and a provider-free OD-6 preflight show zero infrastructure failures at the exact SHA to be booked. It SHALL use the isolated Capture_Arena copy, host port 8360, player loopback port 8370, no port 8357, frozen per-run attempt/time caps, and redacted evidence under `tmp/router-rollout/v2-network/n3/<run-id>/`.

#### Scenario: N3 lifecycle gate is booked
- **WHEN** the exact-SHA preflight is clean and the required booking is approved
- **THEN** the primary runs the declared lifecycle scenarios within the frozen caps, preserves expected-versus-observed checks and teardown evidence before cleanup, and records PASS, FAIL, or BLOCKED from the evidence rather than process exit status alone

#### Scenario: N3 preflight or required evidence is incomplete
- **WHEN** the preflight has an infrastructure failure, a required scenario or cleanup assertion is missing, or a cap is exceeded
- **THEN** the gate is not PASS, no later live attempt is automatically retried, and the primary records FAIL or BLOCKED with the exact evidence path
