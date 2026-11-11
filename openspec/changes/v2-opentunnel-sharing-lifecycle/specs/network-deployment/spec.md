# Spec Delta

## ADDED Requirements

### Requirement: Production companion SHALL use a pinned install-relative executable

Production sharing SHALL use upstream OpenTunnel v0.6.2 only at `runtime/opentunnel/v0.6.2/<asset-stem>/opentunnel` beneath the installation root. It SHALL select asset stem and SHA-256 from the later packaging change's pinned manifest; this change resolves only the mapping and does not distribute binaries. Only macOS arm64 and Linux arm64 are supported; every other OS/architecture SHALL fail closed with bounded `unsupported_platform`. It SHALL NOT search `PATH`, download, or install.

#### Scenario: Production resolver refuses an absent or misplaced companion
- **WHEN** the manifest-selected binary is absent, outside the resolved installation root, or inside `.venv` or `venv`
- **THEN** Start sharing fails before process execution with a bounded diagnostic and does not download, install, or search `PATH`

#### Scenario: A platform pair outside the N0-evidenced matrix is selected
- **WHEN** the host OS/architecture pair is not macOS arm64 or Linux arm64
- **THEN** the controller reports `unsupported_platform`, starts no companion process, and performs no `PATH` search, download, or installation

#### Scenario: An approved platform pair resolves through the pinned manifest
- **WHEN** the host is macOS arm64 or Linux arm64 and the pinned packaging manifest contains that platform's asset stem and SHA-256
- **THEN** the resolver selects only `runtime/opentunnel/v0.6.2/<asset-stem>/opentunnel` beneath the installation root and uses the manifest-pinned digest; it invents no asset stem or digest

### Requirement: Production profile state SHALL be private and isolated

Production sharing SHALL use a dedicated NEQ profile in private per-profile XDG state outside the repository and campaign data. Tunnel private keys SHALL remain there. Only the existing N1 verifier may be stored, in private 0600 storage; plaintext credentials, cookies, and invitations SHALL NOT be persisted. No OS-keychain dependency is introduced. Unrelated profiles SHALL remain untouched.

#### Scenario: Production profile state is private
- **WHEN** the production profile is created or opened
- **THEN** its XDG state is private, the existing N1 verifier is stored with 0600 permissions outside repository/campaign data, and unrelated profiles and repository/campaign files remain untouched

### Requirement: Production identity bootstrap SHALL be explicit and leave no background service

Identity bootstrap SHALL be an explicit facilitator action, once per dedicated XDG profile. It SHALL run guarded `up -> status -> down` and require positive ownership evidence before foreground `serve`. Uncertainty SHALL fail closed without further mutation. Evidence SHALL be bounded, redacted, and credential-free. N0 spike-only checks SHALL be reimplemented behind the controller with tests.

#### Scenario: Facilitator initializes a profile identity once
- **WHEN** the facilitator explicitly initializes an uninitialized dedicated profile
- **THEN** the controller runs guarded `up -> status -> down`, records completion only after successful checks, and does not run bootstrap automatically at host startup or login

#### Scenario: Identity bootstrap proves no helper or service remains
- **WHEN** bootstrap finishes before foreground `serve`
- **THEN** positive executable/profile/ownership checks prove no service-manager entry, helper, or background process remains, including when `PATH` is empty

#### Scenario: Identity bootstrap evidence is uncertain
- **WHEN** any executable, profile, ownership, service-manager, or process evidence is missing or ambiguous
- **THEN** the controller fails closed before `serve`, makes no further changes, leaves uncertain resources untouched, and reports only bounded redacted credential-free evidence

### Requirement: Sharing readiness SHALL fail closed

The sharing controller SHALL report `ready` and return an invitation only after the game is available, player assets are verified and served, the authenticated player listener is healthy on loopback, N1 authentication is configured, the owned tunnel route passes its health check, and the controller has bound the exact companion-reported HTTPS origin to N1 validation for that same generation.

#### Scenario: A startup dependency is not ready
- **WHEN** any readiness prerequisite is missing or fails during startup
- **THEN** no invitation is returned, the public route is not advertised, the state is failed or degraded, and local facilitator play remains available

#### Scenario: The full stack becomes ready
- **WHEN** every readiness prerequisite passes for the same owned sharing generation
- **THEN** the controller reports `ready` and makes the HTTPS invitation available only to the local facilitator surface

### Requirement: The companion origin SHALL be bound by exact match for one generation

After companion status reports route readiness for the active generation, and before the controller reports that generation ready, it SHALL bind only the exact HTTPS scheme, host, and port reported by that status to N1 validation. The binding SHALL be generation-scoped and cleared on stop, failed, degraded, or rotation. Changed or unparsable origins SHALL fail closed; the host surface SHALL NOT be exposed. Invitations SHALL be URL-only.

#### Scenario: The ready generation binds its exact HTTPS origin
- **WHEN** companion status reports a parseable HTTPS origin after route readiness for the active generation
- **THEN** the controller adds only that exact scheme/host/port to N1 Origin validation and its exact host/port authority to Host validation before publishing the invitation

#### Scenario: Wildcard, suffix, and subdomain variants are presented
- **WHEN** a player request uses a wildcard, suffix match, or subdomain instead of the exact bound Host or Origin
- **THEN** N1 rejects the request and does not expose the host surface

#### Scenario: HTTP or a mismatched port is presented
- **WHEN** a player request uses an HTTP Origin or a Host/Origin with a port different from the exact bound HTTPS origin
- **THEN** N1 rejects the request

#### Scenario: Companion status origin is unparsable or changes
- **WHEN** companion status contains an unparsable origin or reports a changed origin for the active generation
- **THEN** the controller fails closed, publishes no invitation, and does not broaden or retain the prior binding

#### Scenario: A stale generation reports an origin
- **WHEN** status from a stale generation reports an otherwise valid HTTPS origin
- **THEN** the controller ignores it and does not add it to N1 validation

#### Scenario: Lifecycle invalidates the origin binding
- **WHEN** sharing is stopped, failed, degraded, or access is rotated
- **THEN** the prior origin binding is cleared and rejected until the active generation passes a fresh status/readiness check

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

### Requirement: Recovery defaults SHALL remain unchanged outside the isolated N3 gate host

Production recovery SHALL retain its existing default maximum of 5 attempts and backoff delays. The gate override SHALL be honored only in the valid isolated N3 gate context and SHALL NOT change production defaults outside that context.

#### Scenario: The isolated live-gate host supplies a valid recovery override
- **WHEN** the process is running in the non-symlink isolated `tmp/combat_capture` copy with `WEB_PORT == 8360`, `NEQ_N3_GATE_RUN_ID` matching `^[a-z0-9-]{8,64}$`, and an integer `NEQ_N3_GATE_MAX_RECOVERY_ATTEMPTS` from 1 through 3
- **THEN** the recovery policy honors that attempt limit, does not exceed the production default of 5, and retains the existing backoff delays

#### Scenario: An override is invalid or supplied outside the isolated gate host
- **WHEN** the override is malformed, outside 1 through 3, or the isolated-copy, port, or run-ID condition is not met
- **THEN** the override is ignored with a bounded reason code, production recovery remains at its default of 5 attempts, and existing backoff delays remain unchanged

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
