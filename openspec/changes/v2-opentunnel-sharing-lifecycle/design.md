# Design

## Context

See `proposal.md` for motivation and `specs/` for the observable contract. N0 evidence covers only OpenTunnel v0.6.2 on macOS arm64 and Linux arm64 (container); the approved resolution matrix is limited to those pairs and does not imply broader native-install support. The later packaging change supplies the pinned asset-stem/SHA-256 manifest. N1 provides a separate same-process player ASGI application bound to `127.0.0.1:8370`, with its own authentication, session, Host/Origin, CSRF, route, and event boundaries. N2 currently starts it only through the development-only `NEQ_PLAYER_DEV_LISTENER=1` opt-in; N3 replaces that temporary activation with explicit facilitator controls, including a separate once-per-profile identity initialization action.

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

The companion resolver MUST use only `runtime/opentunnel/v0.6.2/<asset-stem>/opentunnel` beneath the installation root and select the asset stem/SHA-256 from the pinned manifest supplied by the later packaging change. This change resolves that mapping only; it does not distribute binaries or define a new manifest. The only approved platform pairs are macOS arm64 and Linux arm64. Every other OS/architecture pair MUST fail closed with the bounded `unsupported_platform` state. The resolver MUST validate path containment, reject `.venv`/`venv` placement, and MUST NOT search `PATH`, download, or install. Dedicated per-profile XDG state remains outside the repository, campaign data, and Python environment; unrelated OpenTunnel profiles are never inspected or changed.

**Simplest alternative considered:** Keep `NEQ_PLAYER_DEV_LISTENER=1` as the production switch. Rejected because it does not provide facilitator-visible consent, readiness, supervision, or revocation and is explicitly temporary in N2.

### 2. Use one serialized, generation-bound lifecycle controller

The controller SHOULD expose the bounded states `off`, `starting`, `ready`, `degraded`, `stopping`, `failed`, and `unsupported_platform`. Each accepted start creates one generation. Start, stop, rotation, and recovery operations for the NEQ profile are serialized; a stop accepted during startup cancels that generation. Repeated start requests return the existing state rather than creating another listener, route, identity, or child process.

Readiness is a conjunction, not a tunnel-process check: the local runtime is available, the player assets pass the N2 manifest/digest check, the authenticated listener is healthy on loopback, a non-empty N1 credential verifier is configured, the owned route is healthy for the same generation, and the controller has bound the exact companion-reported HTTPS origin to N1 validation for that generation. The invitation remains withheld until every predicate passes. On startup failure, unwind only resources proven to belong to that generation and leave local host play available.

The companion runs as an owned foreground child. Its output is drained but not persisted raw; status uses bounded reason codes. Relay recovery uses a finite, specified backoff budget. Exhaustion withdraws the invitation and leaves local gameplay available. Recovery never resubmits gameplay input; the existing N1/N2 client protocol owns resynchronization.

**Concurrency-heavy implementation:** generation cancellation, serialized operations, and shutdown/recovery races require deterministic fake-process tests. Do not use real sleeps, relay access, or timing luck as the primary concurrency proof.

**Simplest alternative considered:** Independent start/stop callbacks that each manipulate processes and listener state. Rejected because a late startup callback could restore a route after stop or create duplicate resources.

### 3. Reuse N1 auth/session authority and keep the invitation credential-free

Credential rotation and revocation use the existing N1 shared-credential verifier and session authority. The plaintext player credential is generated once per issuance, shown once to the local facilitator, and never persisted, logged, passed in an argument, placed in the environment, or included in evidence. Only the existing N1 verifier is stored in private 0600 storage outside the repository and campaign data; this change has no OS-keychain dependency. Rotation issues a new credential and invalidates sessions, pre-login challenges, CSRF proofs, and connected sockets before accepting the new verifier; stop closes the listener and all sessions. A new sharing generation cannot revive an old session. Recovery means rotation, not retrieval of the prior plaintext credential.

Copy invitation exposes only the currently healthy HTTPS player URL to the local facilitator UI. It is reachability, not authentication: no password, verifier, cookie, private key, or access token is embedded. The host listener, host routes, and host Socket.IO surface are never tunneled.

**Security-heavy implementation:** credential handling, session invalidation, and secret redaction must remain inside the N1 threat boundary. Do not create a second auth/session model.

### 4. Bind only the exact companion-reported HTTPS origin to N1

After companion status reports route readiness for the active generation, and before the controller reports that generation ready, the controller SHALL add only its exact HTTPS scheme, host, and port to the N1 player boundary: the matching exact Host authority and `https://host:port` Origin. No wildcard, suffix, or subdomain matching is allowed; HTTP is never allowed, and this binding does not expose the host surface. A changed or unparsable status origin fails closed. The binding is generation-scoped and is cleared on stop, failed, degraded, or rotation; a stale-generation result cannot restore it. Rotation requires a fresh status/readiness check before any binding is restored. The invitation remains URL-only.

### 5. Prove lifecycle failures with injected companions, then define a separate live gate

Provider-free tests SHOULD inject a fake companion and controllable supervisor/process adapter. They must cover supported and unsupported platform pairs, missing/misplaced binaries, unavailable assets or credentials, once-per-profile identity bootstrap and uncertain ownership, empty-`PATH` checks, foreground startup failures, readiness ordering, exact-origin positive and negative cases, duplicate/concurrent starts, stop-during-start, child exit, relay loss/recovery/exhaustion, cleanup failure, restart/orphan ownership, access rotation, and secret-bearing output. Origin negatives include wildcard, suffix, subdomain, HTTP, port mismatch, unparsable or changed status, stale generation, and use after stop, degraded state, or rotation. The fake must assert no real DNS, socket, subprocess, relay, or provider activity. These tests prove software behavior only.

The later live lifecycle gate is primary-orchestrator-owned and distinct from N4 gameplay. Before booking, its exact-SHA, provider-free OD-6 preflight runs the entire declared lifecycle row set against a stubbed companion on an isolated `Capture_Arena` copy. The preflight takes the live-window lock because it starts the host on port 8360; it is not a gate PASS and consumes no provider or relay attempt budget. It records invocation identity, row/fixture coverage, stop/cap fault checks, identity freeze, and teardown, with zero infrastructure failures required at the exact SHA to be run.

Only after focused tests and a clean exact-SHA preflight may the primary orchestrator run the later lifecycle gate under its separate authorization and booking. Use an isolated copy, host port 8360, player loopback port 8370, never port 8357 or the installed campaign. Preserve expected-versus-observed checks and redacted teardown evidence under `tmp/router-rollout/v2-network/n3/<run-id>/`; preflight artifacts go under its `preflight/` subdirectory. Freeze platform set, scenario rows, attempt/time caps, and invocation before preflight and do not change them between preflight and live run. No automatic retry is allowed. A missing row, infrastructure failure, cap breach, or cleanup failure is FAIL or BLOCKED, never PASS from exit status alone.

This lifecycle gate does not establish installer/update readiness, N4 external gameplay, browser compatibility, or overall Phase 3 completion; those remain outside this change.

### Live gate contract

The frozen primary-owned live-gate contract, including manifest `n3-live-lifecycle-v3`, its rows, caps, lock protocol, platform verdicts, state-root policy, and evidence rules, is specified in [`reports/n3-live-gate-contract.md`](reports/n3-live-gate-contract.md). L03 starts the local runtime exactly once through host-side Socket.IO polling and permits only its single priced startup narration attempt within the USD 0.05 per-run and USD 1.00 cumulative narration caps. Seed/profile validation is fail-closed and occurs before host side effects. The recovery-attempt override is sandbox-only; production defaults and backoff delays remain unchanged outside the isolated gate host.

## Risks / Trade-offs

- [A stale or reused PID could target an unrelated process] -> Require positive executable/profile/ownership evidence; fail closed and leave uncertain resources untouched.
- [Relay recovery can outlive a facilitator's stop request] -> Bind recovery to the active generation and serialize cancellation/cleanup.
- [A relay URL may remain known after stop] -> Remove the owned route, stop the player listener, invalidate sessions, and require fresh explicit start; URL secrecy is not treated as access control.
- [A bootstrap check may leave an identity helper or service behind] -> Require positive executable/profile/ownership proof, including under empty `PATH`; uncertainty fails closed without further mutation, and reimplement N0 checks behind the controller rather than assuming spike-only mechanisms are shippable.
- [A changed or broad public origin may weaken the player boundary] -> Bind one exact HTTPS origin per active generation and clear it on lifecycle invalidation or uncertain status.
- [A facilitator may lose the one-time plaintext credential] -> Recovery is an explicit rotation that invalidates existing sessions and proofs before accepting the new verifier; plaintext is never recovered from storage.

## Migration Plan

1. Record the resolved owner/Overseer rulings below and freeze the matching specs before runtime implementation.
2. Implement the companion path/profile and one-time identity bootstrap, private N1 verifier store, exact origin binding, then the serialized controller, host-only controls, session revocation, and provider-free failure tests in task order.
3. Replace the N2 development-only listener opt-in only when the explicit control path is ready. Ordinary startup remains sharing-off; rollback is Stop sharing, confirm owned resources are gone, and retain local host operation.
4. Build the provider-free OD-6 preflight and offline lifecycle tests. The separate primary-owned v3 live gate permits only the bounded L03 startup narration described in the frozen contract; do not run a live tunnel or lifecycle gate as part of implementation or validation of this change.
5. The primary orchestrator may run the separately authorized lifecycle gate only after focused tests and the clean exact-SHA OD-6 preflight. Packaging, N4, and release work remain separate.

No campaign or character-state migration is introduced.

## Rulings (resolved)

Ruling id: `neq-n3-open-questions-20261111` (recorded 2026-11-10T18:42:42Z).

1. **Production companion mapping:** APPROVED. Resolve only `runtime/opentunnel/v0.6.2/<asset-stem>/opentunnel`, install-relative, with no `PATH` search, download, or installation. The approved matrix is limited to the N0-evidenced pairs macOS arm64 and Linux arm64. Every other OS/architecture pair fails closed with the bounded `unsupported_platform` state. The later packaging change supplies the pinned manifest containing asset stems and SHA-256 values; this change resolves the mapping only.
2. **Production identity bootstrap:** APPROVED as a distinct, explicit, facilitator-initiated, once-per-profile action in dedicated per-profile XDG state outside the repository. The sequence is guarded `up -> status -> down`. Before foreground `serve`, positive executable/profile/ownership evidence must prove that no service-manager entry, helper, or background process remains; the proof must account for empty-`PATH` behavior. If evidence is uncertain, fail closed, change nothing further, leave uncertain resources untouched, and report. Evidence is redacted and credential-free. N0 spike-only mechanisms are not shipped by assumption; reimplement them behind the controller with tests.
3. **Credential storage:** APPROVED with no OS-keychain dependency in this change. For each issuance, generate the plaintext player credential once and show it once to the local facilitator; never persist, log, pass it as an argument, place it in the environment, or include it in evidence. Store only the existing N1 verifier in private 0600 storage outside the repository and campaign data, never in Git. Recovery means rotation: issue a new credential and invalidate sessions, challenges, CSRF proofs, and sockets before accepting the new verifier. OS-keychain integration is deferred to a later change.
4. **Public invitation/origin:** APPROVED as exact-match and controller-owned. The only player Origin/Host addition is the exact HTTPS scheme, host, and port reported by companion status after readiness, bound to N1 validation for that generation only. No wildcard, suffix, or subdomain matching is allowed; HTTP and host-surface exposure are not allowed. Clear the binding on stop, failed, degraded, and rotation. A changed or unparsable origin fails closed. Invitation remains URL-only.
