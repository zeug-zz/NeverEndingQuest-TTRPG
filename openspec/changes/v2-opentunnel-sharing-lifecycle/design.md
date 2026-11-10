# Design

## Context

See `proposal.md` for motivation and `specs/` for the observable contract. N0 established OpenTunnel v0.6.2 feasibility on macOS arm64 and a Linux arm64 container; that evidence does not establish a native Linux install contract or approve production identity bootstrapping. N1 provides a separate same-process player ASGI application bound to `127.0.0.1:8370`, with its own authentication, session, Host/Origin, CSRF, route, and event boundaries. N2 currently starts it only through the development-only `NEQ_PLAYER_DEV_LISTENER=1` opt-in; N3 replaces that temporary activation with explicit facilitator controls.

The approved network plan keeps the host listener local, uses the upstream companion only for the player listener, and requires explicit consent before changing network reachability. Packaging of the companion and prebuilt player assets belongs to a later change.

## Goals / Non-Goals

**Goals:**

- Replace environment-only player-listener startup with a facilitator-owned sharing lifecycle while keeping local play independent of the companion.
- Keep one Python runtime and tunnel only the existing player listener.
- Make start, recovery, stop, session revocation, and owned-resource cleanup deterministic and testable without a real relay.
- Define the primary-owned lifecycle evidence path without running it in this planning change.

**Non-Goals:**

- Binary download/installation, installers, prebuilt asset delivery, updates, or clean-install claims.
- N4 browser/gameplay scenarios, external player gameplay, relay self-hosting, custom domains, or a tunnel fork.
- Windows server support, new player routes/events, host tunnelling, direct LAN fallback, and party-size or `MULTIPLAYER_MODE` changes.

## Decisions

### 1. Keep the companion controller at the host/player boundary

The implementation SHOULD place companion resolution and lifecycle ownership in a narrow `web/extensions/` module, with local host controls calling that boundary. The N1 player ASGI app remains the only tunnel target and receives no lifecycle handlers. Host changes that wire the controller into the existing host surface carry `# TABLETOP MODE:`. No second Python runtime, host-app proxy, or Node runtime is introduced.

The companion resolver MUST use only the proposed install-relative path in `network-deployment`, validate resolved-path containment, and reject `.venv`/`venv` paths. It MUST NOT search `PATH`, download, or install. The later packaging change supplies verified assets. Dedicated per-profile XDG state remains outside the repository, campaign data, and Python environment; unrelated OpenTunnel profiles are never inspected or changed.

**Simplest alternative considered:** Keep `NEQ_PLAYER_DEV_LISTENER=1` as the production switch. Rejected because it does not provide facilitator-visible consent, readiness, supervision, or revocation and is explicitly temporary in N2.

### 2. Use one serialized, generation-bound lifecycle controller

The controller SHOULD expose the bounded states `off`, `starting`, `ready`, `degraded`, `stopping`, and `failed`. Each accepted start creates one generation. Start, stop, rotation, and recovery operations for the NEQ profile are serialized; a stop accepted during startup cancels that generation. Repeated start requests return the existing state rather than creating another listener, route, identity, or child process.

Readiness is a conjunction, not a tunnel-process check: the local runtime is available, the player assets pass the N2 manifest/digest check, the authenticated listener is healthy on loopback, a non-empty N1 credential verifier is configured, and the owned route is healthy for the same generation. The invitation remains withheld until every predicate passes. On startup failure, unwind only resources proven to belong to that generation and leave local host play available.

The companion runs as an owned foreground child. Its output is drained but not persisted raw; status uses bounded reason codes. Relay recovery uses a finite, specified backoff budget. Exhaustion withdraws the invitation and leaves local gameplay available. Recovery never resubmits gameplay input; the existing N1/N2 client protocol owns resynchronization.

**Concurrency-heavy implementation:** generation cancellation, serialized operations, and shutdown/recovery races require deterministic fake-process tests. Do not use real sleeps, relay access, or timing luck as the primary concurrency proof.

**Simplest alternative considered:** Independent start/stop callbacks that each manipulate processes and listener state. Rejected because a late startup callback could restore a route after stop or create duplicate resources.

### 3. Reuse N1 auth/session authority and keep the invitation credential-free

Credential rotation and revocation use the existing N1 shared-credential verifier and session authority. Rotation invalidates sessions, pre-login challenges, CSRF proofs, and connected sockets before accepting the new verifier; stop closes the listener and all sessions. A new sharing generation cannot revive an old session.

Copy invitation exposes only the currently healthy HTTPS player URL to the local facilitator UI. It is reachability, not authentication: no password, verifier, cookie, private key, or access token is embedded. The host listener, host routes, and host Socket.IO surface are never tunneled. The exact trusted public Host/Origin derivation remains subject to the owner ruling below; the existing N1 validation rules are not relaxed.

**Security-heavy implementation:** credential storage, session invalidation, secret redaction, and public-origin selection must be reviewed against the N1 threat boundary before exposure. Do not create a second auth/session model.

### 4. Prove lifecycle failures with injected companions, then define a separate live gate

Provider-free tests SHOULD inject a fake companion and controllable supervisor/process adapter. They must cover missing/misplaced binaries, unavailable assets or credentials, identity-helper/foreground startup failures, readiness ordering, duplicate/concurrent starts, stop-during-start, child exit, relay loss/recovery/exhaustion, cleanup failure, restart/orphan ownership, access rotation, and secret-bearing output. The fake must assert no real DNS, socket, subprocess, relay, or provider activity. These tests prove software behavior only.

The later live lifecycle gate is primary-orchestrator-owned and distinct from N4 gameplay. Before booking, its exact-SHA, provider-free OD-6 preflight runs the entire declared lifecycle row set against a stubbed companion on an isolated `Capture_Arena` copy. The preflight takes the live-window lock because it starts the host on port 8360; it is not a gate PASS and consumes no provider or relay attempt budget. It records invocation identity, row/fixture coverage, stop/cap fault checks, identity freeze, and teardown, with zero infrastructure failures required at the exact SHA to be run.

Only after focused tests and a clean exact-SHA preflight may the primary orchestrator run the later lifecycle gate under its separate authorization and booking. Use an isolated copy, host port 8360, player loopback port 8370, never port 8357 or the installed campaign. Preserve expected-versus-observed checks and redacted teardown evidence under `tmp/router-rollout/v2-network/n3/<run-id>/`; preflight artifacts go under its `preflight/` subdirectory. Freeze platform set, scenario rows, attempt/time caps, and invocation before preflight and do not change them between preflight and live run. No automatic retry is allowed. A missing row, infrastructure failure, cap breach, or cleanup failure is FAIL or BLOCKED, never PASS from exit status alone.

This lifecycle gate does not establish installer/update readiness, N4 external gameplay, browser compatibility, or overall Phase 3 completion; those remain outside this change.

## Risks / Trade-offs

- [A stale or reused PID could target an unrelated process] -> Require positive executable/profile/ownership evidence; fail closed and leave uncertain resources untouched.
- [Relay recovery can outlive a facilitator's stop request] -> Bind recovery to the active generation and serialize cancellation/cleanup.
- [A relay URL may remain known after stop] -> Remove the owned route, stop the player listener, invalidate sessions, and require fresh explicit start; URL secrecy is not treated as access control.
- [N0 implementation details may be mistaken for production approval] -> Keep production identity setup behind the explicit owner decision below; do not ship the N0 empty-PATH test mechanism by assumption.

## Migration Plan

1. Resolve the OPEN QUESTIONS below and record owner/Overseer rulings before runtime implementation. Update the existing specs/design first if a ruling changes a contract.
2. Implement the companion path/profile and credential boundary, then the serialized controller, host-only controls, session revocation, and provider-free failure tests in task order.
3. Replace the N2 development-only listener opt-in only when the explicit control path is ready. Ordinary startup remains sharing-off; rollback is Stop sharing, confirm owned resources are gone, and retain local host operation.
4. Build the N3 provider-free preflight/lifecycle harness. Do not run a live tunnel or lifecycle gate as part of implementing or validating this planning change.
5. The primary orchestrator may run the separately authorized lifecycle gate only after focused tests and the clean exact-SHA OD-6 preflight. Packaging, N4, and release work remain separate.

No campaign or character-state migration is introduced.

## OPEN QUESTIONS - OWNER / OVERSEER APPROVAL REQUIRED BEFORE IMPLEMENTATION

1. **Production companion mapping:** Approve the exact install-relative v0.6.2 asset-stem mapping and the macOS/Linux architecture matrix. The spec proposes `runtime/opentunnel/v0.6.2/<asset-stem>/opentunnel`; N0 evidence alone does not certify all native artifacts.
2. **Production identity bootstrap:** N0's guarded `up -> status -> down` and empty-PATH/service-manager checks were approved for spike use, not production. Approve the production identity-minting sequence and the evidence required to prove that no background service or helper remains before foreground `serve` starts.
3. **Credential storage:** Approve the OS-specific storage mechanism and recovery behavior for the facilitator's player credential/verifier. It must satisfy the existing N1 credential contract and the private-storage/no-log/no-Git requirements; no plaintext environment, argument, or evidence fallback is assumed.
4. **Public invitation/origin:** Approve how the relay-provided HTTPS host/origin is bound to N1 Host/Origin validation and displayed/copied locally. The existing contract requires a player-only target and URL-only invitation; this question does not authorize host-surface exposure or weaken N1 checks.
