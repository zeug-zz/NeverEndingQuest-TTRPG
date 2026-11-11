# Spec Delta

## Purpose

Defines the fork-owned browser client and its player-boundary assets for a coherent, least-privilege N2 gameplay experience.

## ADDED Requirements

### Requirement: Player client assets SHALL use bounded same-origin routes

The player shell and its versioned, content-hashed assets SHALL be served only by the existing player ASGI `GET /` and `GET /static/player/<asset-id>` routes. Asset IDs SHALL resolve only through a bounded manifest; responses SHALL use same-origin URLs, `nosniff`, a restrictive CSP, and cache policy appropriate to immutable hashed assets. The host Flask application SHALL NOT serve these assets.

#### Scenario: Player shell and hashed assets are served
- **WHEN** a browser requests the player shell and each asset ID named by its manifest
- **THEN** the player listener returns only those player assets with the required headers and the host Flask application serves none of them

#### Scenario: Unknown asset ID is requested
- **WHEN** a browser requests a static player asset ID absent from the bounded manifest
- **THEN** the player listener rejects it without reading an arbitrary file or falling back to a host route

### Requirement: Player asset and protocol incompatibility SHALL fail closed

The player shell and bundle SHALL identify their build and protocol versions. HTTP snapshot requests and Socket.IO handshakes SHALL identify the client build and protocol; the listener SHALL reject mismatches before protected data or gameplay work and provide a clear diagnostic. A failed asset preflight SHALL NOT advertise listener readiness or fall back to the host UI.

#### Scenario: Client build or protocol version is incompatible
- **WHEN** a browser presents a client build or protocol version not supported by the listener
- **THEN** the listener rejects the snapshot or socket connection with an explicit compatibility error and the client displays a resynchronization or reload message without submitting gameplay input

#### Scenario: Build manifest is missing or corrupt
- **WHEN** the explicit player listener is started without a valid manifest, a complete asset set, or matching asset digests
- **THEN** it fails closed with a clear diagnostic, opens no ready player surface, and does not serve the facilitator UI

### Requirement: Player UI SHALL present a coherent safe gameplay projection

The client SHALL render the ordered shared transcript, shared active PC, approved character sheets and portraits, relevant initiative and combat state, and bounded busy state from server projections. Browser state SHALL remain a cache; untrusted narrative and player text SHALL render without executable raw HTML.

#### Scenario: One-PC party is presented
- **WHEN** an authenticated client hydrates a 1-PC snapshot and receives subsequent player events
- **THEN** it shows the single approved sheet, shared active PC, transcript, relevant combat state, and busy state without requiring a multi-PC-only model

#### Scenario: Four-PC party stays coherent across clients
- **WHEN** the host and at least two authenticated clients use a 4-PC party while transcript, active PC, sheets, initiative, combat, or busy state changes
- **THEN** all clients converge on the same server-projected state and ordered transcript without exposing unprojected or host-only fields

#### Scenario: Narrative contains HTML or an unsafe URL
- **WHEN** projected narrative or player text contains raw HTML or an unsafe URL scheme
- **THEN** the player display treats it as non-executable text and does not load the unsafe destination

### Requirement: Player selections and input SHALL preserve N1 race and receipt semantics

The client SHALL use only the N1-allowlisted player routes and events, including `player.snapshot.request`, `player.active_pc.select`, and `player.input.submit`. It SHALL carry the current protocol and active-PC revision, display typed accepted, duplicate, busy, stale, rejected, and uncertain outcomes, and SHALL never retarget input or automatically replay an uncertain submission after an instance change.

#### Scenario: Another client changes the active PC before input admission
- **WHEN** a client submits input with an obsolete active-PC revision or a no-longer-active character
- **THEN** the server returns a stale receipt, the client refreshes authoritative state and surfaces the stale result, and no PC receives the input

#### Scenario: Input is busy, rejected, or uncertain
- **WHEN** the server returns a busy, rejected, or uncertain receipt
- **THEN** the client visibly identifies that outcome and does not present it as accepted or automatically resubmit it

#### Scenario: Client retries or reconnects after an instance change
- **WHEN** a client retries an existing request ID or reconnects with a new server instance
- **THEN** it displays the original or uncertain result as applicable, resynchronizes from an authoritative snapshot, and never causes duplicate enqueue or LLM work

### Requirement: Player bundle SHALL exclude host-only capabilities

The production player bundle SHALL exclude toolkit, settings, lifecycle, party-editing, and debug code and entry points. A built-output content/dependency test SHALL fail when a forbidden host-only module or capability marker is present.

#### Scenario: Built bundle contains a host-only capability
- **WHEN** the bundle-content test scans the generated player output
- **THEN** it rejects any host-only module or capability marker and the bundle is not accepted for serving

### Requirement: Local host startup SHALL be independent of player assets

Ordinary host startup and local facilitator operation SHALL NOT require Node.js, a frontend package installation, or a valid player bundle. Missing or broken player assets SHALL affect only an explicitly started player listener.

#### Scenario: Host starts with sharing disabled and no client build
- **WHEN** the host starts with the player listener disabled and the player bundle missing or broken
- **THEN** no player listener opens and ordinary local facilitator operation remains available without invoking Node.js

#### Scenario: Opted-in listener cannot load its client build
- **WHEN** the development/test listener is explicitly requested but asset preflight fails
- **THEN** the listener remains not-ready, reports the failure, and leaves local facilitator operation available

### Requirement: N2 listener startup SHALL be explicit and loopback-only

N2 development and gate startup SHALL require an explicit off-by-default opt-in and the existing facilitator-supplied scrypt verifier, and SHALL bind only to `127.0.0.1:8370`. This temporary opt-in SHALL be replaced by N3 facilitator sharing controls.

#### Scenario: Development opt-in is absent
- **WHEN** ordinary host startup has no N2 development/test opt-in
- **THEN** the player listener remains stopped

#### Scenario: Development opt-in is valid
- **WHEN** an authorized facilitator enables the N2 development/test opt-in with a valid verifier and client bundle
- **THEN** the listener starts only on loopback port 8370 and still exposes only player capabilities

### Requirement: Managed N2 dispatches SHALL share a bounded attempt ledger

The managed N2 driver SHALL inject a 30-attempt budget into its owned sandbox. Each non-loopback HTTPX dispatch SHALL reserve one slot in a cross-process locked ledger before transport send; loopback requests SHALL not reserve. SDK retries, router fallbacks, concurrent work, and inherited child processes SHALL share the ledger.

#### Scenario: Thirty attempts are allowed and the next is refused before dispatch
- **WHEN** 30 non-loopback HTTPX dispatches have been reserved in one managed run and another dispatch is requested
- **THEN** the first 30 may enter the transport, the next is recorded as refusal 31, and that request does not reach the transport

#### Scenario: Retries, fallbacks, and concurrent provider work share one budget
- **WHEN** SDK retries, router fallback, background work, or multiple inherited-environment processes dispatch non-loopback HTTPX requests in one run
- **THEN** each dispatch reserves from the same ledger, and concurrent requests cannot send more than 30 non-loopback dispatches to transport

#### Scenario: Loopback requests do not consume provider budget
- **WHEN** HTTPX sends to loopback host or player services during the gate
- **THEN** the request reaches its transport without a provider-attempt reservation

### Requirement: Managed N2 budget activation SHALL fail closed

Budget activation SHALL require all run variables and a proven isolated root. Partial/invalid activation or ledger failure SHALL refuse startup or dispatch. Without activation variables, ordinary startup and HTTPX behavior SHALL remain unchanged.

#### Scenario: Missing or unsafe activation fails closed
- **WHEN** activation variables are partial/invalid, the runtime root is not isolated, or the ledger cannot safely reserve
- **THEN** startup or the pending dispatch is refused before transport; without activation variables no guard or ledger side effect is installed

### Requirement: Managed N2 gate SHALL preserve budget and identity evidence

Live N2 runs SHALL require managed mode and a matching active ledger before gameplay input. The driver SHALL copy the ledger after teardown and fail the run on any refusal. Receipt-derived provider identity SHALL remain separate; ledger records SHALL omit headers, bodies, credentials, and query strings.

#### Scenario: Managed gate verifies budget and preserves separate evidence
- **WHEN** a live N2 gate starts or finishes its managed host lifecycle
- **THEN** it refuses non-managed live execution before endpoint contact or evidence creation, requires matching active-budget evidence before browser gameplay, copies the ledger after teardown, and reports any refusal as FAIL without using receipt-derived provider identity as a budget count

### Requirement: N2 browser selection SHALL preserve the default

The driver SHALL default to `chrome+firefox`. `--browsers chrome` SHALL launch one Chrome player and the separate Chrome host context, without launching Firefox or substituting a second Chrome player.

#### Scenario: Chrome-only records partial browser coverage
- **WHEN** the driver runs with `--browsers chrome`
- **THEN** it launches only one Chrome player and the separate Chrome host context

#### Scenario: Default browser behavior is unchanged
- **WHEN** no browser selector is supplied
- **THEN** the driver requests Chrome and Firefox and preserves the existing independent-player coverage

### Requirement: N2 evidence SHALL retain per-check browser coverage

The catalog SHALL identify Firefox-dependent checks. Chrome results SHALL remain independently visible; omitted Firefox checks SHALL be BLOCKED with reason `firefox-unavailable-in-sandbox`. `run.json` and `summary.json` SHALL record requested/run sets, actual launched-role versions, and blocked checks. Overall status SHALL NOT be PASS when any check is BLOCKED.

#### Scenario: Chrome-only coverage is explicitly incomplete
- **WHEN** the driver completes a Chrome-only run
- **THEN** it records each Chrome check and each Firefox-dependent check separately, preserves the Firefox block reason and actual Chrome/host versions in both run records, and reports overall BLOCKED rather than PASS

### Requirement: N2 gate execution SHALL stop on the first unsafe outcome

The driver SHALL validate Playwright status and required persisted evidence before managed lifecycle work. Lifecycle scenarios SHALL run serially and stop after failure, timeout, interruption, malformed/missing evidence, non-Firefox block, or provider-budget stop. Unexecuted scenarios/checks SHALL be `BLOCKED` with the stop cause. Expected Firefox-only blocks SHALL NOT stop valid Chrome checks or lifecycle execution. Automatic retry/resume is forbidden.

#### Scenario: Failed Playwright result stops managed lifecycle
- **WHEN** the Playwright child fails, or a required persisted Playwright scenario/check is missing, malformed, failed, or blocked outside the expected Firefox-only case
- **THEN** no managed lifecycle scenario is dispatched, each unexecuted lifecycle scenario/check is recorded `BLOCKED` with the stop cause, and cleanup plus final evidence are still attempted

#### Scenario: Managed lifecycle stops at the first failure
- **WHEN** a managed lifecycle scenario fails, times out, has a non-Firefox block, or cannot safely continue under the provider-attempt budget
- **THEN** no later lifecycle scenario is dispatched, the remaining required scenario/check evidence is recorded `BLOCKED`, and bundle restoration, teardown, and final evidence are still attempted

#### Scenario: Firefox-only blocks do not stop Chrome coverage
- **WHEN** Chrome checks have valid outcomes and the only `BLOCKED` checks are Firefox-dependent checks with reason `firefox-unavailable-in-sandbox`
- **THEN** applicable Chrome checks and managed lifecycle scenarios continue, while the overall browser coverage remains non-PASS

### Requirement: N2 setup failure evidence SHALL be safe and complete

The setup hook SHALL persist fixed-stage evidence before teardown without arbitrary exception or credential values. It SHALL record readiness, nullable early build/protocol metadata, screenshot outcomes, and zero gameplay execution. Missing or empty scenario results require valid setup evidence; unexecuted scenarios remain `BLOCKED` with `executed: false`.

**Guidance (SHOULD):** Use the shared player-version reader; test the production screenshot sanitizer through its real DOM/evaluate path.

#### Scenario: Browser setup fails before gameplay
- **WHEN** the Playwright `beforeAll` hook fails at any setup stage
- **THEN** it captures the fixed-stage setup record and safe-or-skipped screenshots before closing pages, records zero executed gameplay scenarios, and the driver records all required scenarios as `BLOCKED`/unexecuted without inventing gameplay observations

#### Scenario: Scenario results are absent after setup failure
- **WHEN** a valid setup-failure record exists and `scenarios.jsonl` is missing or empty
- **THEN** the driver preserves the original `missing` or `empty` classification, stops managed lifecycle work, and does not misclassify that state as malformed JSON; malformed, unreadable, or contradictory results still fail closed

#### Scenario: Authenticated player is disconnected during setup
- **WHEN** a player page has the fixed expected origin, canonical `NeverEndingQuest player` heading, exact `Log out` button, no password field, and a known `Connected`, `Disconnected`, `Connecting...`, or `Loading player snapshot...` status
- **THEN** the hook masks form/editable and recognized credential-bearing content before capturing the screenshot, even when the status is `Disconnected`

#### Scenario: Early connection failure preserves protocol metadata
- **WHEN** the authenticated player shell is available but the normal `Connected` wait fails
- **THEN** evidence records `protocol_version` when readable and null when unknown, without bypassing the wait or executing gameplay

#### Scenario: Player screenshot authentication is unknown
- **WHEN** the page is a login page, has an unknown status, lacks the canonical authenticated shell, contains a password field, or has the wrong origin
- **THEN** no screenshot is captured and the setup record contains a bounded skip reason

### Requirement: N2 socket request diagnostics SHALL be bounded and credential-safe

Request diagnostics SHALL retain only allowlisted metadata for exact player-origin `/socket.io/` requests, without query strings, raw URLs, or header/cookie values. Unobservable fields SHALL be `unknown`. The 128-record and 32,768-byte serialized JSONL limits SHALL apply cumulatively for the full run, including records already flushed to disk; excess observations SHALL be counted as omitted.

#### Scenario: Socket request metadata is captured
- **WHEN** exact player-origin Socket.IO requests are observed
- **THEN** diagnostics contain only bounded allowlisted metadata and safe booleans/`unknown`, never raw headers, cookies, query strings, or full URLs

### Requirement: Managed N2 host output SHALL discard raw text

The managed host SHALL drain and discard stdout/stderr immediately. Evidence SHALL contain only bounded counters, truncation state, process exit metadata, and bounded process counts across restarts.

#### Scenario: Managed host emits process output
- **WHEN** the owned host writes stdout or stderr and is stopped or restarted
- **THEN** raw text is discarded and the evidence retains only bounded counters and process metadata

### Requirement: N2 Playwright driver output evidence SHALL exclude raw text

The driver SHALL attach bounded counters to the actual Playwright child stdout/stderr streams and persist `driver-output.json` with only capped per-stream byte counts/truncation flags, exit status, an allowlisted signal, and a fixed spawn category. Raw child chunks and arbitrary exception text SHALL NOT be persisted in this artifact; existing terminal redaction remains unchanged.

#### Scenario: Playwright child emits failure output
- **WHEN** the Playwright child writes arbitrary or credential-bearing stdout/stderr and exits or fails to spawn
- **THEN** the driver output artifact contains only bounded counters and safe exit/spawn metadata, never the emitted text or arbitrary spawn error details

### Requirement: Agent-run credentials SHALL be confined and ephemeral

`--agent-run` SHALL require `--manage-sandbox-host --browsers chrome`. It SHALL validate the managed sandbox and bundle before credential generation, reject inherited owner credentials, and generate none during dry-run. It SHALL keep the throwaway password and verifier out of argv, logs, and evidence.

#### Scenario: Safe managed agent-run starts with fresh credentials
- **WHEN** an agent requests a live Chrome-only managed run with no inherited owner credentials and confinement preflight succeeds
- **THEN** the password is generated in-process, the repository auth helper creates its verifier through stdin, the Playwright child receives only the password, and the owned host child receives only the verifier

#### Scenario: Unsafe agent-run or dry-run refuses credential generation
- **WHEN** agent-run is requested without managed Chrome-only mode, with a non-empty inherited owner credential, with failed confinement preflight, or in dry-run mode
- **THEN** the driver refuses the incompatible live mode or prints only the dry-run plan, without generating a credential or starting a child process

### Requirement: N2 handshake observation SHALL be a single inert player pass

The existing N2 harness SHALL provide an opt-in `--observe-handshake` mode for one real player login and Socket.IO handshake observation with a P1 party. The mode SHALL use one Chrome player only and SHALL NOT run gate scenarios, gameplay, or lifecycle work; the default N2 gate behavior SHALL remain unchanged.

#### Scenario: Handshake observation runs without host UI or gameplay
- **WHEN** the managed handshake-observation mode runs
- **THEN** it uses only the P1 Chrome player, performs no host browser or host UI HTTP request (host readiness is TCP-only), submits no gameplay input, and runs no P4 or N2 gate/lifecycle scenario

#### Scenario: Default N2 gate remains unchanged
- **WHEN** the driver runs without `--observe-handshake`
- **THEN** it retains the existing default browser set and full N2 gate flow, independently of the one-pass observation mode

### Requirement: Handshake observation SHALL prove zero provider dispatches

The observation SHALL require an active managed provider ledger before login and SHALL prove zero reservations and zero refusals before login, after the pass, and in the final ledger. Any reservation, refusal, or missing, invalid, or inactive ledger SHALL prevent a PASS.

#### Scenario: Active ledger remains at zero
- **WHEN** the active ledger is checked before login, after the observation, and after owned-host teardown
- **THEN** each check records zero reservations and zero refusals and the evidence distinguishes active-zero from a guard that did not start

#### Scenario: Ledger is inactive or a dispatch is reserved
- **WHEN** the ledger is absent, invalid, inactive, records any reservation, or records any refusal
- **THEN** a reservation or refusal is recorded as FAIL, an absent/invalid/inactive ledger is BLOCKED without claiming zero use, the observed guard state is retained, evidence and owned teardown are attempted, and the mode does not retry

### Requirement: Handshake evidence SHALL be bounded and teardown-safe

Observation evidence SHALL reuse the existing allowlisted Socket.IO diagnostics and evidence writer, preserve unobservable booleans as `unknown`, and exclude credential/header values. Setup evidence and pending diagnostics SHALL be written before the player page/browser closes; owned teardown and final port probes SHALL be attempted on every outcome.

#### Scenario: Handshake diagnostics are persisted
- **WHEN** the player-origin Socket.IO handshake is observed
- **THEN** evidence contains only bounded method, path, status, transport, and safe Origin/Host/session-cookie booleans, with unobservable values recorded as `unknown`

#### Scenario: Setup, teardown, or port verification fails
- **WHEN** setup, evidence writing, owned-host teardown, final bind-and-close port probing, or existing booking release fails
- **THEN** the failure is recorded when possible, cleanup and release are attempted, and the run stops without retry

### Requirement: Handshake dry-run SHALL preflight the full runtime import graph

`--dry-run --observe-handshake` SHALL import and resolve every runtime module used by the mode without endpoint access, port binding, process/browser/listener launch, provider dispatch, credential generation, sandbox seeding, or evidence-file creation. An unresolved import SHALL fail the preflight.

#### Scenario: Full import preflight succeeds without side effects
- **WHEN** the mode is run with `--dry-run --observe-handshake`
- **THEN** its complete runtime import graph is loaded and no endpoint, listener, provider, credential, seed, or evidence-file side effect occurs

#### Scenario: Runtime module cannot be resolved
- **WHEN** an import required by the observation mode is unresolved
- **THEN** the dry-run exits nonzero and side-effect tripwires confirm that no observation or setup side effect occurred

### Requirement: Player Socket.IO handshakes SHALL use WebSocket only

The browser player SHALL use exactly `transports: ["websocket"]` for `/player` Socket.IO, preserving existing connection and client-auth options. It SHALL NOT use HTTP polling initially or as fallback. Server Host, Origin, CSRF, session, and client-auth checks SHALL remain unchanged. WebSocket failure SHALL fail closed.

**Guidance (SHOULD):** Cover blocked-WebSocket behavior in N4 network checks.

#### Scenario: Same-origin player connection uses WebSocket with existing authentication
- **WHEN** an authenticated player connects through the browser client
- **THEN** its first and only Socket.IO transport is WebSocket, with the existing session cookie and client-build/protocol auth, and no polling request or fallback

#### Scenario: WebSocket authority or authentication checks reject invalid handshakes
- **WHEN** an Engine.IO WebSocket handshake has valid Origin, Host, session cookie, and client auth, or has missing/wrong Origin, wrong Host, or invalid existing authentication
- **THEN** the valid handshake is accepted and each invalid handshake is refused by the unchanged player-server checks

#### Scenario: Network blocks WebSocket
- **WHEN** the network cannot establish the player's WebSocket connection
- **THEN** the client remains disconnected/fails closed and does not attempt HTTP polling; N4 public-tunnel/network checks exercise this condition
