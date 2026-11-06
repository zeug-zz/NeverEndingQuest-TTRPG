# Design

## Context

See `proposal.md` and the two change specs for motivation and observable behavior. The current `web/extensions/player/` package has an isolated ASGI/Socket.IO app and an explicit loopback listener, but the listener is not wired into host startup. Its HTTP registrations already include `GET /` and `GET /static/player/<asset-id>`; its Socket.IO app currently registers only `player.input.submit`, while N1 also allows `player.snapshot.request` and `player.active_pc.select`. The player asset module contains only login-shell CSS, and current projections cover party/sheets and busy state rather than the N2 transcript and combat view. The existing active-PC adapter calls `utils.pc_manager.set_active_pc_checked`.

The primary-run sandbox browser probe is recorded at `tmp/n2/browser-probe/RESULT.txt`. On 2026-11-06, Chromium headless shell 1223, Chrome for Testing 1223, system Chrome, and Edge all failed at launch; Playwright Firefox and WebKit were not installed. The probe records Node 22.22.3 and npm 10.9.8 locally. This is an evidence constraint, not a product-browser restriction.

## Goals / Non-Goals

**Goals:**
- Keep one authoritative Python runtime and use its canonical readers and writers for every player projection or mutation.
- Keep player asset, route, event, session, and emission boundaries separate from the host Flask application.
- Preserve one- and four-PC behavior through the same contract, with finite synchronization and asset bounds.
- Make the player build and optional listener independently diagnosable without affecting ordinary local host play.

**Non-Goals:**
- OpenTunnel, direct LAN sharing, installer or prebuilt-distribution work, and N3 sharing controls.
- Replacing the facilitator UI, assigning PCs to players, or adding a second runtime or state owner.
- A markdown renderer, clickable arbitrary URLs, host-only interface parity, mobile support, TTS distribution, or provider changes.
- Editing `MULTIPLAYER_MODE`, party-size gates, or `plans/`.

## Decisions

### 1. Use the existing player root and asset route

**MUST:** Build a fork-owned React/TypeScript application under `web/frontend/`. The player ASGI listener will serve the unauthenticated login shell and React entry document at its existing `GET /`, then serve only exact manifest entries at its existing `GET /static/player/<asset-id>`. The host Flask app will not mount, proxy, or serve either route for player assets. All API, socket, media, script, and stylesheet URLs will be relative to the player origin; no `localhost`, LAN address, host filesystem path, or environment-specific URL will be baked into the bundle.

**MUST:** The build manifest will contain a finite set of ASCII asset IDs matching `[A-Za-z0-9._-]{1,128}`, each mapped to a file beneath the build root, content type, byte length, and full digest. The listener will resolve the requested ID only by exact manifest lookup, verify every listed file and digest before readiness, and reject unknown IDs. It will never form a filesystem path directly from a request ID.

**MUST:** `GET /` and login/error responses will be `no-store`. Verified content-hashed assets may use `public, max-age=31536000, immutable`. All asset responses will include `X-Content-Type-Options: nosniff` and a restrictive CSP with same-origin scripts, styles, images, forms, and connections; no inline script, `unsafe-eval`, wildcard CORS, or external asset origin is needed. The client will use same-origin Socket.IO and media URLs.

**Decision:** Reuse `GET /` plus `GET /static/player/<asset-id>`, which are already in the N1 `player-capabilities` allowlist. Do not add `/client`. This is the smallest route surface and does not require an allowlist expansion. The route layout was APPROVED by the Overseer on 2026-11-06, recorded in `plans/v2-narrative-overview.md` at commit `f35ff232` ("N2 proposal rulings"). Any later new route/event first needs a MODIFIED `player-capabilities` requirement and inventory-test update. Do not silently grow the allowlist.

**Decision:** Ignore `web/frontend/dist/` and `web/frontend/node_modules/` in N2; commit frontend source, `package.json`, and `package-lock.json`, not generated output. The N2 development and gate flow explicitly runs the Node build before starting the player listener. N3 owns packaging and delivery of prebuilt assets, so committing a generated bundle now would create a second, stale-prone source of truth.

**Simplest alternative considered:** Serve one unversioned asset or copy the bundle into the host Flask static tree. Rejected because it loses immutable cache identity or crosses the player/host boundary.

### 2. Fail closed on incomplete or incompatible client assets

The explicit listener startup will load and validate the manifest, every referenced asset, each digest, and the manifest protocol version before reporting ready or binding the serving stack. Missing, corrupt, incomplete, or unsupported assets produce a bounded `PlayerClientAssetsError` diagnostic; there is no host-UI fallback and no partially-ready player listener. A failure affects only the player listener; the host startup path logs the diagnostic and continues ordinary local operation.

The shell and bundle carry a `client_build_id` and protocol version. HTTP `GET /api/player/snapshot` requires exactly one `X-NEQ-Client-Build` header and one `X-NEQ-Protocol-Version` header (the latter is canonical decimal text); Socket.IO connect auth requires exactly `client_build_id` (string) and `protocol_version` (integer), with no unknown keys. For both transports, Host/Origin and session authentication run first; only an authenticated request can receive a version diagnostic. The listener then compares both values to the verified current manifest before snapshot projection, socket registration, or gameplay work. Missing, malformed, stale-build, and unsupported-protocol values produce the bounded `client_version_mismatch` diagnostic (HTTP 409 with only `{"error":"client_version_mismatch"}`; Socket.IO connect refusal with the same fixed diagnostic). The response does not include the expected build ID: the non-cacheable shell already exposes it, and the client can reload that shell without expanding diagnostic disclosure. Keep the existing version-1 command, receipt, snapshot, and event envelopes exact; do not add fields to those strict envelopes. The non-cacheable shell and content-hashed assets make normal refreshes select the current build, while the explicit check handles stale or mismatched clients.

### 3. Use a small, build-only frontend toolchain

**Decision:** Use Vite, TypeScript, React, and React DOM in `web/frontend/`; use Vitest with jsdom for component and store tests. Use React DOM test utilities rather than adding a separate component-testing library. Use `socket.io-client` for the existing player namespace. Node 22.x and npm 10.x are build/test tools only; host runtime and normal startup import no Node tooling and never invoke npm.

**Decision:** Render projected narrative, transcript, and player input as ordinary React text nodes. Do not use `dangerouslySetInnerHTML`, clickable arbitrary URLs, or an HTML/Markdown rendering package. Server-projected media remains addressed by approved media IDs. This is the smallest safe rendering path and avoids a new sanitizer dependency; formatting can be proposed separately if the text-only N2 surface proves inadequate.

The dependencies were APPROVED by the Overseer on 2026-11-06, recorded in `plans/v2-narrative-overview.md` at commit `f35ff232` ("N2 proposal rulings"): exactly `react`, `react-dom`, `socket.io-client`, `vite`, `typescript`, `@types/react`, `@types/react-dom`, `vitest`, `jsdom`, and dev-only `playwright`, at exact current stable versions. Commit the lockfile and run `npm ci` inside `web/frontend/` only. Before merge, the implementation PR carries the direct/transitive license inventory and a clean `npm audit --audit-level=low`. Any copyleft, unknown or unlicensed package, or any added package, returns for review. Pin the Node setup action to a commit SHA and record provenance in the PR. Do not add a license-scanner package just for this slice.

**Simplest alternative considered:** Use a CDN or server-side HTML template with inline JavaScript. Rejected because it adds an external asset origin or grows the host-facing UI instead of establishing a fork-owned player bundle.

### 4. Complete the N1 player event set without expanding it

Register `player.snapshot.request` and `player.active_pc.select` alongside the existing `player.input.submit`, and register the already-spec-allowed `player.snapshot` emission. Align the implementation allowlist constants to the unchanged N1 `player-capabilities` route/event/emission set. The inventory test must continue to assert actual registrations equal the allowlists and that host-only surfaces remain unreachable. No additional path, namespace, event, or emission is part of this design.

`player.snapshot.request` returns the versioned snapshot only to its requesting player socket. `player.active_pc.select` validates an exact current party member and expected revision through the existing checked active-PC writer; on success it publishes the new canonical selection, while stale or rejected selections return a bounded player error and cause a refresh. `player.input.submit` continues through the existing typed gateway and deduplication. The React client renders every receipt status, binds pending UI state to its request ID and exact PC/revision, and never changes the character context of an already-submitted request.

Use the N1 envelope, cursor, request-ID, receipt, session-epoch, and server-instance contracts unchanged. Same-instance retries return the original receipt and enqueue at most once. Refresh/reconnect performs snapshot or bounded replay only; it never resubmits input or invokes LLM work. After an instance change, prior submissions are visibly uncertain and require resynchronization or user confirmation, never automatic replay. The UI does not claim universal exactly-once execution. Python remains authoritative for validation, mechanics, persistence, and provider calls.

### 5. Publish host changes from canonical state, not global emissions

Extend the server projection to the N2 read-only fields needed for ordered transcript, active-PC selection, approved sheets/portraits, initiative/combat, and busy state. Keep field allowlists and size bounds. Read party and character state through canonical PC/state readers and combat from its canonical encounter owner; read transcript through the existing canonical transcript source. Do not pass raw host event payloads, raw files, hidden plot/GM notes, or debug data into a player event.

Add narrow host integration hooks at the committed host transcript-output, host active-PC selection, and initiative/combat update seams. Each host edit will carry `# TABLETOP MODE:`. After the canonical writer/commit succeeds, a thread-safe in-process publisher will submit only a typed change/revision to the existing player listener. The listener will serialize publication through its own event loop and `PlayerSyncCoordinator`, read the current canonical projection, and emit only the existing `player.event` envelope to authenticated player sockets. Host-global emissions remain unchanged and player sockets are never attached to their rooms or broadcasts. If publication cannot be completed, record a bounded diagnostic and force an authoritative player resync; do not silently lose a player-visible change or start parallel gameplay/provider work.

The same stable event IDs and snapshot/replay boundary cover host and player changes. The transcript projection retains stable item IDs and order. Active-PC selection uses the shared canonical CAS revision, and input admission remains explicitly bound to the submitted character and observed revision. One-PC and four-PC parties use the same projection schema; no party-size gate or per-player PC ownership is added.

**Simplest alternative considered:** Forward selected host Socket.IO emissions or attach player sockets to host global emissions. Rejected because emissions are not canonical state and can contain host-only data. A second runtime or event-specific browser state owner is also rejected.

### 6. Keep N2 listener activation explicit

The off-by-default `NEQ_PLAYER_DEV_LISTENER=1` host-startup opt-in was APPROVED by the Overseer on 2026-11-06, recorded in `plans/v2-narrative-overview.md` at commit `f35ff232` ("N2 proposal rulings"). It is for N2 development and gate runs, requires the existing scrypt verifier, starts only the same-process player listener on `127.0.0.1:8370`, and allows no bind/port override. Without the flag, the listener remains stopped. With the flag but missing credentials or invalid assets, host play continues unaffected. All host edits are marked `# TABLETOP MODE:`. This is temporary and replaced by N3.

**Simplest alternative considered:** Start the player listener on every host launch or invoke Node from `run_web.py`. Rejected because ordinary local play must remain independent of sharing and build output.

### 7. Browser evidence and N2 gate

Use this evidence order:

1. The Overseer APPROVED installing Playwright Firefox and WebKit into the user's Playwright cache, using the lockfile's pinned `playwright` version, after task 2.1 and with no other system changes. A sandbox denial is reported, not worked around.
2. The external owner-run driver requires separate review. The declared player clients are independent Chrome and Firefox instances; run the facilitator UI in a separate host browser context. The `playwright` package is dev-only and is not a server dependency.
3. With no real-browser path, the gate is BLOCKED. Socket-only or headless-protocol checks may supplement the evidence but SHALL NOT replace it.

On 2026-11-06 the sandbox probe found Chromium headless shell 1223, Chrome for Testing 1223, system Chrome, and Edge unable to launch; Playwright Firefox (`firefox-1522`) and WebKit (`webkit-2287`) were absent. Preserve that fact and the source path `tmp/n2/browser-probe/RESULT.txt` in the evidence bundle; do not claim a browser PASS from socket tests.

The Overseer APPROVED the browser evidence rulings on 2026-11-06, recorded in `plans/v2-narrative-overview.md` at commit `f35ff232` ("N2 proposal rulings"). The live N2 gate needs its own booking and is serialized with S's SP3b; it is not runnable until S releases port 8360. Use an isolated `Capture_Arena` copy only: host UI on 8360, player ASGI listener on loopback 8370, no port 8357 and no installed campaign. Write evidence under `tmp/router-rollout/v2-network/n2-<run-id>/`. Record build SHA, browser and OS versions, party shape, scenario, expected and observed results, and actual model/provider identity if a gameplay turn invokes a provider. The gate covers 1-PC and 4-PC parties; at least two player clients plus host UI; host transcript/order and active-PC sync; sheets, initiative/combat, and busy state; PC-switch race; repeated request ID; busy input; refresh/reconnect; server-instance change; missing and broken bundle; and a browser probe for host-only routes/events. Missing a real-browser path or required assertion is BLOCKED/FAIL, not waived.

## Risks / Trade-offs

- [Root route differs from plan section 6 `/client`] -> Reuse avoids allowlist growth; obtain Overseer review before implementation and change the capability requirement first if `/client` is required.
- [Ignored build output can be absent on a developer machine] -> Host startup remains independent; explicit listener startup fails closed with a clear diagnostic, and N2 gate setup builds assets before opt-in.
- [Frontend dependency supply-chain and license surface] -> Obtain approval before install, exact-pin direct dependencies, commit the lockfile, audit the lock, review all licenses, and add CI `npm audit` coverage.
- [Host and player event paths can race or disagree] -> Publish only after canonical commit, serialize through the existing sync coordinator, use stable cursors, and force snapshot resync on publication failure.
- [Real browsers may remain unavailable in the primary sandbox] -> Follow the declared external owner-run path; if that also fails, Gate N2 remains BLOCKED.

## Migration Plan

1. Complete the read-only upstream `/play` provenance inventory and secure the required owner approvals before adding/installing frontend dependencies or touching host startup.
2. Build and test the player package; generate the ignored local bundle. Start the listener only through the reviewed off-by-default opt-in and valid facilitator-supplied scrypt verifier.
3. Roll out behind the disabled-by-default opt-in. If any client, manifest, projection, or publication check fails, leave the player listener stopped and retain ordinary host operation. No campaign or character data migration is introduced.
4. Run provider-free tests and security checks before the separately booked live N2 gate. N3 later replaces the development opt-in and owns packaged prebuilt assets.

Rollback is to unset `NEQ_PLAYER_DEV_LISTENER`, stop the explicitly owned player listener, and leave the host local interface running. Do not remove or alter canonical game state, the installed campaign, or unrelated listener processes.

## Overseer / Owner Rulings

1. APPROVED by the Overseer on 2026-11-06, recorded in `plans/v2-narrative-overview.md` at commit `f35ff232` ("N2 proposal rulings"). Route layout: shell at player `GET /`, assets at `GET /static/player/<asset-id>`, no `/client`; any later new route/event first needs a MODIFIED `player-capabilities` requirement and inventory-test update.
2. APPROVED by the Overseer on 2026-11-06, recorded in `plans/v2-narrative-overview.md` at commit `f35ff232` ("N2 proposal rulings"). `NEQ_PLAYER_DEV_LISTENER=1` is off by default, loopback `127.0.0.1:8370` only, no bind/port override, existing scrypt verifier required, host play unaffected on failure, host edits marked `# TABLETOP MODE:`; temporary, replaced by N3.
3. APPROVED by the Overseer on 2026-11-06, recorded in `plans/v2-narrative-overview.md` at commit `f35ff232` ("N2 proposal rulings"). Dependencies are exactly `react`, `react-dom`, `socket.io-client`, `vite`, `typescript`, `@types/react`, `@types/react-dom`, `vitest`, `jsdom`, and dev-only `playwright`, at exact current stable versions; commit the lockfile; `npm ci` inside `web/frontend/` only. Before merge, the implementation PR carries the direct/transitive license inventory and clean `npm audit --audit-level=low`. Any copyleft, unknown or unlicensed package, or added package, returns for review. Node setup action is pinned to a commit SHA with provenance recorded in the PR.
4. APPROVED by the Overseer on 2026-11-06, recorded in `plans/v2-narrative-overview.md` at commit `f35ff232` ("N2 proposal rulings"). `web/frontend/dist/` and `node_modules/` stay gitignored in N2; prebuilt distribution is N3.
5. APPROVED by the Overseer on 2026-11-06, recorded in `plans/v2-narrative-overview.md` at commit `f35ff232` ("N2 proposal rulings"). Playwright Firefox and WebKit installation into the user's Playwright cache is authorized, using the lockfile's pinned version, after task 2.1 and with no other system changes; report sandbox denial, do not work around it. External owner-run driver requires separate review. With no real browser path the gate is BLOCKED and socket-only evidence never passes. The live gate (host 8360, player 8370, isolated Capture_Arena) needs its own booking and is serialized with S's SP3b.
