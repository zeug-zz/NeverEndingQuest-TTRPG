# Design

## Context

See `proposal.md` for motivation and the three capability deltas for behavior. N0 selected a separate loopback ASGI/Socket.IO application in the host process, served by Uvicorn on its own thread/event loop, with the existing Flask-SocketIO host app remaining local-only. The authoritative runtime is already in-process and queue-driven; the player listener must not become a second state owner. N0 exercised the inert transport stack, not coexistence with the real runtime.

The N0 route/event inventory is a baseline, not a permanent count: re-enumerate the host surface during implementation and fail if any current route or event has no explicit capability classification. The current party schema also omits the existing `active_character` field and has no active-PC revision; the implementation must make this contract explicit without adding party-size gates.

## Goals / Non-Goals

**Goals:**
- Keep the player app, session state, and Socket.IO namespace structurally separate from host routes, handlers, cookies, and global emissions.
- Keep cross-thread access narrow: typed commands enter the existing game-input queue; safe projections leave through canonical readers and a player-only publisher.
- Make bounded behavior and active-PC concurrency deterministic enough to implement and test before any browser client or tunnel exists.

**Non-Goals:**
- Starting the player listener during ordinary host startup, enabling OpenTunnel, or changing host startup/packaging.
- Building a React client, inviting testers, changing gameplay mechanics, or replacing the existing validated input pipeline.
- Adding named accounts, per-player PC ownership, direct LAN discovery, or a second runtime/process.

## Decisions

### 1. Separate ASGI application and explicit runtime gateway

**MUST:** Implement a player package under `web/extensions/player/` that constructs its own HTTP ASGI app, Socket.IO `AsyncServer`, and `/player` namespace. Run it only through an explicit start operation, bound to `127.0.0.1:8370`; ordinary `run_web.py` startup remains unchanged and player sharing defaults off. Configure the single Uvicorn server instance with the tested `websockets` backend, one worker, a 16 KiB WebSocket frame limit, and no reload. Keep the host Flask-SocketIO app on its existing local-only path and do not mount, proxy, or reuse its routes, handlers, sessions, or emissions.

The gateway is the sole coupling to the runtime. It accepts validated typed commands, uses a bounded thread-safe admission path into the existing game-input queue, and obtains read-only data through canonical state readers. It does not call mechanics, providers, arbitrary action dispatch, or persistence directly. Player-visible events are explicitly published to the player namespace/rooms after the existing runtime has validated and committed the relevant state; host broadcasts are never forwarded wholesale. Host changes needed to connect these seams are narrow and marked `# TABLETOP MODE:`.

**SHOULD:** Keep application construction dependency-injected so provider-free tests can exercise the real boundary with controlled runtime queues and canonical-state fixtures without launching the web app or invoking an LLM.

**Alternatives considered:** Filtering the existing Flask app or wrapping its Socket.IO handlers was rejected because default routes and global emissions would remain reachable. A second process was rejected for N1 because it adds IPC and duplicate-state risks without benefit for the selected same-process runtime. A full `run_web.py` startup integration is deferred until sharing UX/lifecycle work.

### 2. Password verifier, session lifecycle, and request identity

**MUST:** Read the facilitator-configured, versioned scrypt verifier from `NEQ_PLAYER_PASSWORD_VERIFIER`; fail closed when it is missing or malformed. Use stdlib `hashlib.scrypt` with `N=32768, r=8, p=1`, a random 16-byte salt, a 32-byte derived key, and `hmac.compare_digest`; accept only the fixed version/parameter tuple and never store or log the cleartext password. Generate a fresh 32-byte session-signing key and server-instance ID at listener start. Use bounded, in-memory session/revocation records so logout revokes immediately and listener/process restart invalidates every prior session without consulting Flask's `SECRET_KEY`.

Use a four-hour session TTL and host-only `Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=14400` cookies with no `Domain`. Require the exact `Host` on every request. Require exact `Origin` for every state-changing HTTP request and Socket.IO handshake/event; if a read request supplies an Origin, require an exact match as well. Use the explicit N1 loopback allowlist (`127.0.0.1:8370` and `http://127.0.0.1:8370`). The minimal `GET /` login shell is non-cacheable and contains a one-use pre-login CSRF nonce paired with a short-lived, host-only cookie; login must echo the nonce and pass Origin validation. After login, return a session-bound CSRF token with no gameplay data; logout and any future state-changing HTTP route must present it. Ignore all forwarding headers. No wildcard CORS is enabled.

The unauthenticated `GET /` and exact-ID `GET /static/player/<asset-id>` serve only a minimal login shell and its public assets. All snapshots, private media, and Socket.IO events require an authenticated session. `GET /` never serves the facilitator UI.

**SHOULD:** Keep the verifier format versioned so its KDF parameters can be reviewed and migrated deliberately; keep the password out of command-line arguments, query strings, cookie values, and logs.

**Alternatives considered:** Copying N0's plain fixture password comparison was rejected because it is not production password storage. Reusing the host Flask secret was rejected because it is hardcoded and shared with a different trust boundary. Adding a password-hashing dependency is unnecessary for the selected scrypt verifier and would expand the dependency change.

### 3. Explicit limits and bounded memory

Use these initial N1 limits as configuration constants with tests at each boundary: 10 login attempts per rolling 60 seconds process-wide; 16 active session records; 8 concurrent player sockets; 16 KiB per HTTP body and Socket.IO event; 1 KiB password and 4 KiB UTF-8 player input; 12 player inputs per rolling minute per session and one admitted player command at a time; 256 KiB per snapshot; 256 replay events and 256 KiB replay bytes; 60 snapshot/expensive reads per minute per session; 30 media reads per minute per session; 1,024 retained input receipts per session (the entire session TTL, no eviction before expiry).

**MUST:** Apply size checks before parsing or projection work, serialize command admission under a lock so the pending-command bound cannot race, return bounded typed overload errors, and refuse new inputs rather than evicting receipt identities when a session reaches its receipt cap. Expired, missing, or cross-instance replay cursors cause a fresh snapshot. These bounds are process/session limits; no client address inferred from a tunnel or forwarding header is an authorization key.

**SHOULD:** Keep the defaults centralized in the player boundary and expose them to tests, not to player payloads. Tune only with evidence and without removing the finite bound.

**Alternatives considered:** Unbounded queues, unlimited replay, and eviction-based deduplication were rejected because they can create memory growth or allow a delayed retry to enqueue the same action again.

### 4. Server-built projections and safe media

**MUST:** Build snapshots/events from canonical state owners using explicit field allowlists; never serialize raw party, character, plot, encounter, or campaign records. Keep the shared transcript and safe player fields separate from host/admin/debug emissions. Resolve media IDs through a server-owned registry and approved roots with containment checks; do not accept paths from clients. Send narrative as text or constrained Markdown with raw HTML disabled and unsafe URL schemes rejected.

Re-enumerate host routes, inbound events, and emissions. Record each current surface as host-only, player projection/typed command, or public login-shell asset; a new unclassified surface fails the inventory test. Assert that the player registration set exactly equals the spec allowlist rather than asserting the historical N0 route/event counts.

**SHOULD:** Test projections with canary privileged values in canonical fixtures and confirm none appear in JSON, emitted events, logs, or media responses. Keep initial player static assets separate from facilitator templates.

**Alternatives considered:** Filtering payloads after forwarding host broadcasts and accepting generic file paths were rejected because both make least privilege dependent on every legacy producer or caller.

### 5. Typed sync, receipts, and active-PC revision

**MUST:** Define one versioned set of input, snapshot, event, and receipt types in `web/extensions/player/`. Each session receives a random session epoch; the listener instance has a random instance ID. The sync coordinator assigns monotonic event IDs, stores only the bounded replay window, and serializes snapshot cursor capture with player-event publication. A projection refresh is replace-by-revision; append-only transcript items carry stable IDs so an event already represented during hydration is idempotently ignored. A reconnect with a contiguous retained cursor replays that range; any gap, expiry, or instance mismatch requires a fresh snapshot.

Deduplicate by session epoch plus request ID, retain the original receipt for that session's lifetime (up to the configured cap), and never automatically re-enqueue across server-instance changes. Receipts report admission only. A typed input carries an explicit character name and active-PC revision; at admission, validate both against canonical party membership and bind the accepted queue item to that exact character so a later tab switch cannot retarget it.

Add optional `active_character` and non-negative `active_character_revision` properties to the party schema. A missing revision in existing state reads as zero. Extend the canonical PC manager writer so every host/player active-PC mutation validates membership, increments the revision on an actual selection change, and persists the selection/revision atomically via the approved JSON writer. Route all existing active-PC write paths through that writer; a stale expected revision is rejected without enqueueing or silently selecting another PC. Do not add per-player ownership or party-size-specific state.

**SHOULD:** Keep receipt/event registries in bounded in-memory structures, since a random process instance invalidates sessions and retries from a previous instance are uncertain by contract. Test snapshot/event races with deterministic barriers and no providers.

**Alternatives considered:** A browser-owned active-PC revision, per-player PC lock, independently written cache, or persisted unbounded event log was rejected. A process-local revision without updating all canonical writers would miss host tab changes; adding the revision beside the canonical selection and funneling all writes through one helper preserves a single source of truth.

### 6. Dependency decision

**MUST:** Adopt the N0-tested ASGI server stack without optional server extras: declare `uvicorn>=0.54.0` and `websockets>=17.4` in `requirements.txt`; pin `uvicorn==0.54.0` and `websockets==17.4` in `requirements-lock.txt`; and resolve the full lock. Raise the `python-socketio` lower bound in `requirements.txt` to `>=5.18.1` and align its lock pin from 5.18.0 to 5.18.1; retain the tested `python-engineio==4.15.1` and existing compatible `h11==0.16.0`/`wsproto==1.3.2` pins. Do not add the N0 driver's `websocket-client` or `requests` as runtime requirements. Reconcile every transitive version with the installed working set and preserve `mitmproxy`'s documented hard caps.

Strictly audit `requirements-lock.txt` with `pip-audit`; only the three tornado CVEs already listed as accepted risk in `SECURITY.md` may be ignored, and only while that exception remains current. A successful requirements-file dry run is also required.

**SHOULD:** Keep direct requirements aligned with repository convention (minimum supported versions in `requirements.txt`, exact pins in `requirements-lock.txt`); avoid `uvicorn[standard]` because the tested base server plus the required WebSocket backend is smaller.

**Alternatives considered:** No new server dependency was rejected because N1 needs the selected ASGI listener. `uvicorn[standard]` was rejected because it adds optional event-loop and HTTP-server packages not required by the tested stack. Not updating the socket.io pin was rejected because it would leave the N0-tested runtime and product lock inconsistent.

## Risks / Trade-offs

- [Async listener and host runtime share a process] -> Keep all cross-thread state behind the typed gateway, use bounded queues and explicit locks, and test start/stop and concurrent admission without providers.
- [A legacy active-PC writer bypasses revision increments] -> Inventory every writer, migrate each to the canonical helper, and test host and player selections against stale input; do not ship if an active writer remains unclassified.
- [Scrypt costs CPU/memory during login] -> Apply the process-wide attempt limit before KDF work, enforce request-size limits first, and test the cap; public exposure remains out of scope for N1.
- [N1 has no browser/tunnel validation] -> Verify cookie attributes, Host/Origin/CSRF decisions, and session behavior with provider-free in-process tests; make no claim about browser SameSite behavior, public TLS termination, or internet readiness.
- [Receipt cap or replay expiry causes a client to resync] -> Return explicit capacity/stale outcomes and require an authoritative snapshot or new session; never evict retained dedup identities or replay an uncertain action.

## Migration Plan

1. The N0 prerequisite is satisfied: PR #89 merged on 2026-11-05, the gate passed, and the change is archived; this plan does not authorize a tunnel, public listener, or live game.
2. Add the bounded player package and its provider-free tests. Keep listener startup explicit and disabled by default; do not alter ordinary host startup.
3. Add the optional party active-PC fields and route all existing active-PC writers through the canonical atomic writer. Existing party files without a revision remain valid and read as revision zero until their next active-PC change.
4. Add the Uvicorn/WebSocket requirements, reconcile the lock and `python-socketio` drift, then run the strict lock audit before any runtime integration is accepted.
5. Run the focused 1-PC and 4-PC integration/security suites and repository checks. The orchestrator records the N1 PASS/FAIL/BLOCKED verdict after reviewing evidence; a green test command alone is not the gate verdict.

Rollback is fail-closed: disable and stop the explicit player listener, leaving local host operation unchanged. The optional party revision is backward-compatible and may remain in existing files; no gameplay state migration or replayed input is required. Revert the new listener/dependency integration only through a reviewed change if N1 cannot pass.

## Owner review required

- No material scope departure is proposed: `network-deployment` remains unchanged; the change is loopback-only, provider-free, requires no live gameplay capture, and leaves React, OpenTunnel, production packaging, and testers out of N1.
- Confirm the additive, optional `active_character_revision` party-schema property (Decision 5) and routing all existing active-PC writers through the canonical writer, since this is a shared schema/runtime-path change.
- The numeric limits in Decision 3 are proposed conservative N1 defaults. Review or tune them before implementation if they do not match the expected number of invited connections, while preserving finite bounds.
- Confirm the dependency decision in Decision 6: `uvicorn` 0.54.0, `websockets` 17.4, and `python-socketio` lock update from 5.18.0 to 5.18.1.
