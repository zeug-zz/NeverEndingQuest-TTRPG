# V2 Server, React Client, and OpenTunnel Network Implementation Plan

Status: DRAFT FOR OWNER REVIEW - not implementation authorization.

Priority: next network-play build after the current LLM-router/combat refactor
is completed, verified, and committed.

Planning date: 2026-10-26.

## 1. Objective and release outcome

Fast-track invited internet test players into real NeverEndingQuest gameplay:
the facilitator starts a macOS/Linux game server, explicitly starts sharing,
and sends an HTTPS invitation URL to players using thin React browser clients.
All players participate in the same authoritative Python tabletop session.

Use upstream OpenTunnel as a managed host-side companion for all remote player
connections in the initial release. Players on the facilitator's LAN use the
same internet-backed tunnel URL as players elsewhere. Offline/direct LAN
transport and Windows game-server packaging are later builds, not prerequisites.

The build combines a bounded refactor of the monolithic browser GUI with secure
network play. Extract reusable presentation and synchronization behavior while
shipping a new React player surface; do not make a complete facilitator UI
rewrite a dependency of getting internet testers playing.

This plan supersedes both deprecated drafts in full:

- [Archived client network draft](archive/client_network.md).
- [Archived client web roadmap](archive/client-web.md).

Their LAN-first sequencing, optional remote password, and deferred internet
security requirements no longer apply. Archived historical documents that point
to those drafts do not restore their authority.

## 2. Approval, sequencing, and authority

1. The owner reviews and approves this consolidated plan.
2. The current LLM-router/combat refactor completes its required verification and
   is committed. Record the integrated baseline SHA; do not infer completion
   from a clean test subset or stale memory.
3. The owner separately authorizes a new `/goal` and isolated worktree build.
   Do not resume, replace, move, or attach this scope to the existing goal.
4. From that committed baseline, inspect the current tree, revalidate this plan's
   assumptions, and create bounded OpenSpec artifacts before runtime edits.
5. Active OpenSpec changes own implementation requirements and acceptance
   criteria, subject to repository rules and accepted ADRs. This document is
   their reviewed planning input, not an already-active implementation change.

Follow ADR-0031 (independent fork) and ADR-0032 (one tabletop runtime, 1..x PCs).
Python remains authoritative for mechanics, narration orchestration, validation,
combat, party state, persistence, publication, and campaign state. React owns
presentation and local UI state only. Network work must not remove or change
`MULTIPLAYER_MODE` or existing party-size gates opportunistically.

## 3. Initial release scope

### Supported platforms and operating model

| Surface | Initial release commitment |
| --- | --- |
| Game server | macOS and Linux; tested platform/architecture combinations declared before packaging |
| Windows | Browser client supported; Windows server build deferred |
| Player browser | Current desktop Chrome/Edge on Windows; Chrome/Firefox on Linux; Safari/Chrome on macOS |
| Remote transport | OpenTunnel HTTPS/WSS, including same-LAN players |
| Facilitator | Existing local host interface at `/`; no tunnel exposure of the admin surface |
| Session shape | One facilitator, one campaign, one authoritative runtime, invited players |
| Party coverage | 1-PC regression floor and 4-PC primary gameplay shape |
| Audio/video | Out of band; TTS/DM Voice remains host-local |

Record exact browser/OS versions in release evidence. Mobile responsiveness is
welcome where cheap but full mobile support is not a first-release gate.

### Player capabilities

- Authenticate, join, disconnect, and reconnect without DM repair.
- See a shared ordered transcript of accepted inputs and narration.
- See and select the shared active PC, with the selection synchronized to host
  and other clients.
- Submit gameplay input through the existing validated game loop.
- View read-only character sheets, portraits, initiative, relevant combat state,
  and shared busy/thinking state.
- Receive clear feedback when input is rejected, queued, stale, or uncertain.

Players cannot manage the party, create/edit PCs, use toolkit/admin/debug
surfaces, change model/settings, save/load/reset, update software, or shut down
or restart the server. Enforce this on the server, not through absent buttons.

### Explicit deferrals

- Offline/direct LAN discovery, transport, TLS setup, and fallback.
- Windows hosting, its tunnel binary/service integration, and installer work.
- Full React facilitator replacement or a rewrite of all legacy browser code.
- Custom OpenTunnel fork, NEQ-operated relay, or relay self-hosting automation.
- Accounts, public registration, multi-campaign lobbies, multi-tenancy, hosting
  services, and horizontal scaling.
- Per-player PC ownership, hard turn locks, observer/claim/assignment workflows.
- Remote TTS distribution, voice/video integration, and full mobile adaptation.

Local facilitator-only operation must remain available without OpenTunnel or
internet. This is not a promise of offline network clients. Tunnel failure must
never silently open a direct LAN listener.

## 4. Architecture and trust boundary

```text
Windows / macOS / Linux player browser
  React /client + same-origin HTTPS requests and Socket.IO
                     |
                     | TLS encrypted to host-side agent
                     v
           Upstream OpenTunnel public relay
                     |
                     | encrypted tunnel traffic
                     v
           NEQ-managed OpenTunnel companion
             local TLS termination on host
                     |
                     | loopback application connection
                     v
          Player-only listener / application boundary
            auth + route/event allowlist + limits
                     |
                     v
          One authoritative Python tabletop runtime
                     ^
                     |
          Local facilitator interface at /
            existing host/admin capabilities
```

OpenTunnel is not a React game server, a gameplay protocol, an account system,
or a player authorization layer. It provides reachability and encrypted
transport. The host-side agent owns the certificate private key and decrypts
the application traffic; the public relay does not see HTTP plaintext under
the documented protocol. Relay availability and certificate issuance remain
external dependencies; this is not an independent security audit or SLA claim.

### Chosen boundary direction

Prefer a distinct loopback player listener/application with a positive route
and Socket.IO event allowlist. Tunnel only that listener, never the existing
unfiltered host port. Its public `/` may redirect to `/client` or login but
must not serve the facilitator interface.

The player boundary and local host must address the same game loop and state
owners. Do not start a second `main.py`, independent game manager, parallel
campaign cache, or unsynchronized writer. Phase 0 must choose and demonstrate
the concrete single-runtime integration. A separate gateway process is
acceptable only with an authenticated, bounded internal interface; a generic
pass-through proxy to the monolith is not an authorization boundary.

If separate listeners prove unsuitable, an alternative shared application must
prove equally strong server-side capability separation across every reachable
route, namespace, event, and emitted payload before approval. This requires an
explicit design update, not an opportunistic port-forward shortcut.

OpenTunnel forwards decrypted bytes without rewriting HTTP. Targets see a
loopback peer and visitor-supplied headers. Therefore:

- Never grant facilitator authority because a request appears local.
- Do not trust `Host`, `Forwarded`, or `X-Forwarded-*` as identity or client IP.
- Define the external HTTPS origin explicitly and validate accepted hosts and
  origins, redirects, Socket.IO handshakes, and cookie/scheme behavior.
- Do not blindly enable proxy-header trust middleware.
- Leave PROXY protocol off unless the selected listener supports and tests it.
  If enabled, use a dedicated restricted listener and a documented trust model.
- Use per-session and global limits even without trustworthy per-client IPs.

Choose a maintained server configuration explicitly supporting Flask-Socket.IO
WebSocket upgrades, polling fallback, concurrency, and shutdown on both host
platforms. Neither a generic WSGI swap nor `allow_unsafe_werkzeug=True` is an
internet-readiness verdict. Preserve one runtime worker/state owner unless a
separately designed architecture proves otherwise.

## 5. Security baseline: required before internet gameplay

### Authentication and session policy

- Remote sharing requires a facilitator-set shared password or equivalently
  strong reviewed invitation credential. No blank/open remote access mode.
- Use established password hashing and random session secrets; replace the
  current hardcoded Flask secret before relying on authenticated sessions.
- Prefer credentials exchanged into an authenticated session rather than
  persistent secrets in URLs. Do not log passwords, tokens, cookies, private
  keys, or complete secret-bearing invitations.
- Use Secure, HttpOnly cookies and an explicit SameSite policy validated for
  the same-origin deployment. Apply CSRF protection to relevant HTTP mutations
  and explicit origin/session checks to Socket.IO connections and mutations.
- Authenticate before snapshots, transcript, private media, or gameplay events
  are delivered. Static login-shell assets may be public if they contain no
  session/game data. Page protection alone is insufficient.
- Define expiry and revocation. Stopping sharing closes active remote sessions;
  restarting sharing must not resurrect previously revoked authorization.
- A tunnel URL is discoverable/shareable reachability, not authentication.

### Authorization and data safety

- Maintain a positive HTTP route, Socket.IO event, namespace, and payload
  capability matrix. Default unknown/new operations to denied for players.
- Reject direct lifecycle, settings, arbitrary internal action dispatch, party,
  toolkit, debug, update, and filesystem operations from player sessions.
- Separate player broadcasts from host/admin emissions. Never attach a player
  socket to unrestricted global emissions as a convenience.
- Render transcript/Markdown safely; sanitize rich content and reject unsafe
  URLs. Do not port unsafe HTML rendering from either legacy or upstream UI.
- Serve only authorized gameplay media via bounded identifiers. Do not expose
  filesystem paths, configuration, raw campaign JSON, or directory traversal.
- Bound login attempts, concurrent connections, message sizes, input frequency,
  pending action queues, snapshot/replay size, and expensive reads. Reject
  overload clearly rather than spawning unbounded LLM work.
- Run focused negative security tests and repository secret/code/dependency
  checks. No new public exploit report or operational audit dump belongs here;
  detailed security findings remain in the established private report location.

Invited friends can still share URLs, submit malformed requests, or have a
compromised browser. A shared password simplifies identity, not authorization.

## 6. React and monolith refactor strategy

Build `web/frontend` as a fork-owned React/TypeScript player application served
at `/client`. Ship its production assets from the player boundary. All player
API/socket/media URLs must be same-origin or use the explicitly approved public
origin; never bake `localhost`, LAN addresses, or host filesystem paths into
browser-visible configuration.

### Upstream reuse policy

- Review the former upstream `/play` implementation as a one-time reference.
- Inventory useful event typing, exact Socket.IO argument arity, stores,
  components, hydration, reconnect, UI-mode, styling, and browser-test patterns.
- Port only selected useful pieces against the fork-native contract. Record
  source revision, license/attribution, disposition, and adaptation rationale.
- Do not merge upstream, inherit its authority assumptions, or create an ongoing
  synchronization obligation. A clean fork-native component is preferable when
  adapting a component costs more than recreating its bounded behavior.

### Refactor by extraction, not replacement

1. Inventory current host behaviors, route/event dependencies, and payloads.
2. Extract typed gameplay DTO/projection and synchronization boundaries first.
3. Build player components and state around those boundaries, not around legacy
   DOM selectors or the full host HTML template.
4. Where useful, route the legacy host through shared adapters/projections while
   preserving its facilitator behavior. Avoid simultaneous competing browser
   state owners or copy-pasted domain logic.
5. Exclude toolkit, settings, lifecycle, party-editing, and debug code from the
   player bundle rather than hiding controls after render.
6. Defer broad host component conversion and deletion of legacy paths until a
   later reviewed parity change. Network play is not gated on a cosmetic rewrite.

React build tools belong to development/release production. End users receive
prebuilt versioned assets; neither players nor normal game-server installers
must install Node.js just to play. Missing/bad player assets produce a clear
sharing diagnostic without breaking local facilitator startup.

## 7. Shared gameplay protocol and reconnect contract

Define the fork-native contract before copying event handlers. Python creates
client-safe projections from canonical state owners; browser stores are caches.
All mutations use the existing validated server-side game loop and canonical
atomic persistence APIs.

The contract must explicitly specify:

- Schema/protocol version, server-instance identity, session epoch, and snapshot
  revision/cursor; incompatible client assets fail clearly rather than drifting.
- Exact event names, argument arity, payload fields, capability class, validation,
  sender-only versus shared delivery, and error/ack behavior.
- A bounded snapshot: recent transcript, active PC, relevant party/sheets,
  initiative/combat, allowed media metadata, and current busy/processing state.
- Ordered server-assigned transcript/event identifiers and a gap-detection rule.
  Establish a snapshot/event boundary so reconnect cannot miss or double-apply
  events produced during hydration.
- Bounded replay where available, otherwise authoritative fresh snapshot. State
  recovery must not depend on retaining an unlimited event log.
- Client request IDs and server-side duplicate suppression for gameplay input;
  define retention limits and behavior across process restarts. Do not claim
  universal exactly-once delivery. Uncertain submissions after restart require
  resync/confirmation, never automatic mutation replay.
- Shared input/busy serialization and bounded queue policy. Busy or stale input
  gets a clear result; reconnect must not retrigger LLM work.
- Server-owned active-PC selection revision and explicit action character
  context. Resolve tab-switch/input races deterministically: reject stale
  context or atomically bind accepted input to the validated PC. Never silently
  apply a submission to a different PC because another client switched tabs.

Shared `active_character` remains a deliberate social-coordination model. No
per-player ownership locks are required. Minimal session identifiers can support
authorization, revocation, deduplication, and diagnostics without introducing
named accounts or a full presence product.

## 8. OpenTunnel packaging and operational lifecycle

Use upstream OpenTunnel, pinned to a reviewed release, as an NEQ-managed native
companion. Do not install it as a Python package, place durable tunnel identity
inside `.venv`, or start by maintaining an OpenTunnel fork.

Phase 0 freezes supported macOS/Linux architectures and actual artifact
availability. Packaging must define:

- Install-relative executable location separate from `.venv`/`venv`, with
  verified release artifacts/checksums, provenance, license notices, and a
  controlled update/rollback policy. Use signatures where upstream provides
  them; do not assume they exist.
- A dedicated NEQ tunnel profile/state location separate from code, secrets in
  configuration examples, campaign state, and any user's unrelated tunnels.
- OS-appropriate private credential/key storage outside Git and logs; no API
  keys or certificate keys read into an agent session or committed artifacts.
- Explicit Start sharing, Copy invitation, status/diagnostics, Rotate/revoke
  access, and Stop sharing controls on the local facilitator surface only.
- Foreground/process-supervised operation where feasible. Avoid an unattended
  start-at-login service by default; document any approved alternative.
- Readiness only after assets, player listener, authentication, and tunnel health
  are verified. Never display a ready invitation for a partially started stack.
- Bounded reconnect/backoff on relay interruption, clear degraded status, and
  retained local gameplay. Do not auto-resubmit gameplay input after recovery.
- Cleanup on Stop sharing, normal exit, launcher restart, failed startup, and
  crash recovery. Reconcile owned orphan processes/routes without terminating
  other profiles or unrelated user services.
- Fail-closed behavior: when sharing is off or the game is down, the companion
  cannot expose host controls or an unauthenticated replacement service.
- Installation/update failures that preserve existing campaigns and local play.

Changing network access is explicit facilitator consent, not an installation
side effect. Keep the host and player listeners loopback-bound in this release.
Relay self-hosting, custom domains, and a custom tunnel implementation are not
part of this packaging work.

## 9. Phased implementation and evidence gates

All phases below are planned, not complete. Keep tasks small enough for focused
verification. No phase passes because a builder reports success or a driver
exits zero. Record actual assertions, platform/browser/provider identity, build
SHA, scenarios, logs with secrets redacted, and expected versus observed results.

### Phase 0 - Committed baseline and transport feasibility

Deliver:

- Confirm the router/combat prerequisite and isolated worktree baseline SHA.
- Inventory host routes, Socket.IO namespaces/events/emissions, state ownership,
  GUI extraction seams, installer paths, and useful upstream React components.
- Recheck current OpenTunnel release, artifact support, license, relay access
  terms/limits, certificate issuance, and documented trust boundary.
- Select the player-listener/runtime integration and maintained serving stack.
- With an inert authenticated fixture, prove asset serving, HTTPS scheme/cookie
  behavior, Socket.IO WebSocket and polling, reconnect, and clean tunnel shutdown.

Gate N0: macOS and Linux feasibility evidenced; no real campaign or unfiltered
host surface publicly exposed. Unsupported platforms, unavailable relay access,
or unsolved runtime ownership leave the gate BLOCKED and require plan review.

### Phase 1 - Secure player boundary and typed shared contract

Deliver:

- Player-only route/event allowlist and server-side host/player authorization.
- Authentication, random secrets, session expiry/revocation, origin/host checks,
  rate/size/connection limits, safe media projection, and rendering policy.
- Typed snapshots, input acknowledgments, active-PC race policy, ordering,
  deduplication, and reconnect contracts.
- A single-runtime integration that preserves local host operations.

Gate N1: unauthenticated and authenticated player negative tests cannot invoke
host operations or receive privileged payloads. 1-PC and 4-PC state projections
and input validation pass. No invitation to gameplay testers yet.

### Phase 2 - React gameplay vertical slice and bounded GUI extraction

Deliver:

- Lean `/client` production bundle, login/join UI, typed stores and components.
- Transcript, shared PC tabs, sheets/portraits, initiative/combat, input, and busy
  state with fork-native TABLETOP parity.
- Safe rendering, snapshot hydration, replay/gap handling, stale-input feedback,
  duplicate suppression, and reconnect/instance-change handling.
- Selective upstream ports with provenance; minimal shared host adapters where
  justified, not a full facilitator conversion.

Gate N2: isolated multi-browser functional checks prove coherent host/player
state for 1-PC and 4-PC parties, no duplicate actions on retry/reconnect, no
stale-PC misapplication, and no host-only bundle/event leakage. Local host works
with sharing disabled or a deliberately broken/missing client build.

### Phase 3 - Managed tunnel, installers, and facilitator sharing UX

Deliver:

- Verified pinned macOS/Linux companion packaging and prebuilt React assets.
- Explicit share/start/status/copy/revoke/stop controls and readiness diagnostics.
- Supervision, recovery, update/rollback, private state, and owned cleanup.
- No required Node runtime, Windows server packaging, or direct LAN fallback.

Gate N3: clean macOS and Linux installs/updates can start local play, start and
stop authenticated remote play, survive relay loss/restart, and leave no
unintended live exposure. Existing campaigns and unrelated tunnels are intact.

### Phase 4 - Orchestrator-owned internet gameplay and release

Deliver:

- Real external-network browser gameplay using the packaged tunnel path, not
  only localhost tests or several tabs on the facilitator's machine.
- Current Windows Chrome/Edge clients against the supported macOS/Linux hosts;
  evidence for the remaining declared browser/platform matrix.
- Facilitator quickstart, player join/reconnect guide, supported-platform matrix,
  network/privacy limitations, failure recovery, and private issue reporting.
- A concise release evidence index and tester-ready build identity.

Gate N4: the primary orchestrator runs and judges required live evidence after
focused tests. Use the isolated Capture_Arena procedure and preserve artifacts
under `tmp/router-rollout/v2-network/<run-id>/`, with network/client evidence in
the same run bundle. Follow the capture skill's copy/port/isolation contract;
adapt the socket/browser drivers through reviewed OpenSpec tasks as necessary.
Do not expose the installed campaign or use ordinary local port 8357 as a test
fixture. Browser sessions must actually exercise the public tunnel URL.

Required live scenarios:

1. Join/login rejection and successful join from a genuinely external network.
2. One host and multiple clients share transcript, PC selection, sheets, and
   processing state during exploration and a normal combat sequence.
3. 1-PC regression session and primary 4-PC session with concurrent clients.
4. Simultaneous PC selection/input, repeated request ID, and busy input produce
   the specified deterministic outcome with no duplicated mechanical mutation.
5. Browser refresh, dropped client, and temporary tunnel interruption restore
   transcript/active-PC/combat/busy state without manual repair or action replay.
6. Server restart with an uncertain submission forces safe resync; stale
   authorizations, instance IDs, and assets cannot silently continue.
7. Stop sharing/revoke removes access from already-connected clients; host play
   continues. Player disconnect cannot shut down or restart the game.
8. Crafted host-only HTTP/socket operations and unsafe rendering/media requests
   are rejected; unauthorized data is not present in snapshots or broadcasts.

Missing required platforms, internet connectivity, credentials, LLM scenarios,
or artifact assertions means BLOCKED/FAIL, not waived completion. Record the
actual runtime model/provider for gameplay captures. Prior router/combat gates
are not rerun wholesale; only new networking scenarios and affected regressions
belong here.

## 10. Proposed OpenSpec outline

These are proposed changes, not artifacts created by this planning update.
Finalize task granularity after Phase 0 inventory; preserve the gate dependencies.

| Proposed change | Main scope / candidate capability specs | Depends on | Exit evidence |
| --- | --- | --- | --- |
| `v2-network-transport-feasibility` | `network-deployment`, runtime/listener decision, inert tunnel spike, port inventory | Committed router/combat baseline | N0 and selected architecture |
| `v2-player-security-contract` | `player-access`, `player-capabilities`, `gameplay-sync` schemas, server-side projection/validation | N0 | N1 and negative security suite |
| `v2-react-player-foundation` | `react-player`, asset build/serving, typed stores, selected upstream provenance, bounded extraction | Reviewed security/sync contract | Minimal authenticated client and component/build tests |
| `v2-player-gameplay-resync` | `gameplay-sync`, tabletop parity, ordering, snapshots, input receipts, stale-PC/reconnect handling | Security boundary and React foundation | N2 and multi-browser regressions |
| `v2-opentunnel-sharing-lifecycle` | `network-deployment`, share controls, pinned companion, health/supervision/revocation | N0; N1 before real exposure | Lifecycle failure-injection evidence |
| `v2-network-packaging-release` | `network-distribution`, macOS/Linux installers, prebuilt assets, operational docs | Functional client and sharing lifecycle | N3 and clean-install/update evidence |
| `v2-internet-gameplay-verification` | `network-gameplay-acceptance`, browser/capture drivers, external-network scenarios | N1-N3 | Orchestrator-owned N4 and tester handoff |

Each proposal should include a bounded design, delta specs with normative
requirements and scenarios, explicit non-goals, tasks, exact test commands, and
evidence locations. Link requirements to gate scenarios rather than repeating
independent checklists that drift. Serving-stack and transport feasibility must
not be hidden inside an otherwise cosmetic React task.

Future separately approved changes: `v2-offline-lan-transport`, Windows hosting,
React facilitator parity, soft identity/observer mode, and PC claim/assignment.
None is required to complete the initial OpenTunnel-first release.

## 11. Validation and completion checklist

The future build must specify and execute exact focused Python/frontend/browser
commands as implementation files and toolchains are selected. Do not fabricate
test filenames or claim a suite exists from this outline.

Required categories:

- Provider-free protocol/projection/auth/authorization/lifecycle unit tests.
- Route/event inventory coverage and negative admin/data-leakage tests.
- React type-check, production build, component/store and safe-rendering tests.
- Browser integration: snapshots, multiple clients, ordered updates, polling
  and WebSockets, reconnect, revocation, stale assets, and input races.
- Tunnel/process failure injection and installer clean-install/update/rollback.
- 1-PC and 4-PC runtime regressions, plus N4 live internet gameplay evidence.
- Applicable secret, code, and dependency security scans without bypasses.

Repository baseline commands, applicable to the changed surface:

```bash
# Dependency-sensitive runtime and test commands use the repository venv.
.venv/bin/python <focused-test-or-driver.py> <reviewed-arguments>
python3 scripts/check_ascii_compliance.py --summary-only
OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate --specs
# Validate each created change as well; record its actual change name/result.
OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate <change-name> --strict
# Only if authored module/JSON data is changed:
.venv/bin/python core/validation/validate_module_files.py --module <ModuleSlug>
```

Placeholder commands above are instructions to select actual targets, not
executable acceptance evidence. Capture setup and runtime hooks also use the
repository venv. Core host edits remain deliberate and marked `# TABLETOP MODE:`;
prefer extensions. Persist state atomically through canonical APIs.

Release is complete only when N0-N4 pass with evidence, supported clean installs
work, documentation is sufficient for invited testers, and no required work is
silently deferred. Evidence must show gameplay, not merely that a URL loads.
The owner then reviews the build for commit/integration under normal branch
protection; this plan does not authorize pushes or bypasses.

## 12. Known baseline facts and design decisions still to verify

At planning review, current code differs from the retired drafts:

- `utils/web_boundary.py` defaults to `127.0.0.1`; `web/web_interface.py` resolves
  the bind address and Socket.IO origins through that boundary. Preserve the
  safe default rather than reintroducing automatic `0.0.0.0` exposure.
- The existing host connection/lifecycle handlers are not a safe player API.
  Audit the full reachable surface before sharing, including initial emissions.
- The current hardcoded Flask session secret must not become the remote-session
  security foundation.
- The host launch path still uses `allow_unsafe_werkzeug=True`; select and verify
  the remote serving stack rather than carrying a local-only assumption online.
- macOS installation uses `.venv`, while the existing Windows installer uses
  `venv`. Neither path should own the native companion or its durable identity.

These are implementation audit inputs, not a public vulnerability report or
claims about the later committed baseline. Recheck after the prerequisite lands.

Phase 0 must settle serving stack/listener integration, supported architectures,
upstream snapshot selection, companion pin/provenance, relay terms/limits,
session credential UX, and reproducible external-network test access. Material
architecture or scope changes require owner review and coherent plan/spec updates.

## 13. References and maintenance

- [Agent guide](../AGENTS.md).
- [ADR-0031: Independent development fork](../adrs/0031-independent-development-fork.md).
- [ADR-0032: Single tabletop runtime](../adrs/0032-single-tabletop-runtime.md).
- [Security policy](../SECURITY.md).
- [Runtime boundary pointer](../docs/architecture/plugin-runtime-roadmap.md).
- [OpenTunnel repository and overview](https://github.com/anomalyco/opentunnel).
- [OpenTunnel target trust boundary](https://github.com/anomalyco/opentunnel/blob/master/docs/trust-boundary.md).
- [OpenTunnel CLI/platform/lifecycle docs](https://github.com/anomalyco/opentunnel/blob/master/packages/cli/README.md).
- [OpenTunnel relay architecture](https://github.com/anomalyco/opentunnel/blob/master/docs/server.md).
- [OpenTunnel MIT license](https://github.com/anomalyco/opentunnel/blob/master/LICENSE).

OpenTunnel references were reviewed during the planning discussion; branch URLs
are mutable. Record immutable release/source references during implementation.
Hindsight records initiative history; active OpenSpec artifacts record approved
implementation progress. Do not append completion history to `AGENTS.md` or
treat archived drafts as current requirements.
