# Proposal

## Why

N0 demonstrated an isolated loopback ASGI/Socket.IO transport, but the existing Flask-SocketIO host surface is not a safe player API: it exposes host operations, global emissions, and a hardcoded Flask session secret. N1 needs a server-enforced player boundary and a typed gameplay protocol before any client or tunnel can use it.

## What Changes

- MUST define a distinct player-only ASGI application on `127.0.0.1:8370` in the existing Python process, with an explicit typed gateway into the one authoritative tabletop runtime; the host Flask application remains local-only and is never proxied or wrapped.
- MUST define password-based session authentication, random signing secrets, expiry and revocation, Host/Origin and CSRF checks, and finite resource limits. N0 fixture primitives may be promoted after review; they are not copied as a substitute for production password hashing or revocation.
- MUST define a positive player HTTP/Socket.IO allowlist, least-privilege server-built projections, safe media references and text-rendering policy, and typed input/snapshot/reconnect contracts.
- MUST preserve host operation with sharing disabled and preserve the shared tabletop runtime for 1-PC and 4-PC parties. Players submit only validated typed commands; Python retains mechanical, narrative orchestration, validation, combat, party-state, and persistence authority.
- MUST make the N1 dependency decision explicit: declare Uvicorn and its required WebSocket backend, pin the ASGI runtime graph in `requirements-lock.txt`, reconcile the `python-socketio` 5.18.0 lock vs 5.18.1 environment drift, and gate on strict lock auditing.
- MUST keep N1 loopback-only and provider-free. It does not expose a public tunnel, invite gameplay testers, or require live gameplay capture.

Non-goals: React client/UI and browser product behavior (N2); production listener startup, sharing UX, OpenTunnel integration, installers, and packaging (N3); public internet gameplay (N4); offline LAN transport, Windows hosting, accounts, multi-campaign hosting, per-player PC ownership, or changes to `MULTIPLAYER_MODE` or party-size gates.

## Capabilities

### New Capabilities

- `player-access`: Isolated loopback listener, authenticated sessions, request-origin policy, revocation, and bounded resource use.
- `player-capabilities`: Deny-by-default route/event access and safe, least-privilege player projections, media, and display content.
- `gameplay-sync`: Versioned snapshots, ordered updates, validated input receipts, active-PC race handling, deduplication, and reconnect recovery.

### Modified Capabilities

None. The existing `network-deployment` capability specifies N0 transport feasibility and the listener decision; this change adds player-facing behavior without changing that transport contract.

## Impact

Future implementation is expected to add focused modules under `web/extensions/` for player contracts, security, projections, gateway, and ASGI listener; make narrowly scoped `# TABLETOP MODE:` host integration edits only where needed; and add provider-free tests under `scripts/`. N1 owns the pinned dependency and lock updates. Existing `web/web_interface.py`, local host routes, canonical state APIs, and 1-PC/4-PC runtime behavior must remain compatible. No product code, tests, dependency files, or main specifications are changed by this proposal.
