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

### Requirement: Agent-run credentials SHALL be confined and ephemeral

`--agent-run` SHALL require `--manage-sandbox-host --browsers chrome`. It SHALL validate the managed sandbox and bundle before credential generation, reject inherited owner credentials, and generate none during dry-run. It SHALL keep the throwaway password and verifier out of argv, logs, and evidence.

#### Scenario: Safe managed agent-run starts with fresh credentials
- **WHEN** an agent requests a live Chrome-only managed run with no inherited owner credentials and confinement preflight succeeds
- **THEN** the password is generated in-process, the repository auth helper creates its verifier through stdin, the Playwright child receives only the password, and the owned host child receives only the verifier

#### Scenario: Unsafe agent-run or dry-run refuses credential generation
- **WHEN** agent-run is requested without managed Chrome-only mode, with a non-empty inherited owner credential, with failed confinement preflight, or in dry-run mode
- **THEN** the driver refuses the incompatible live mode or prints only the dry-run plan, without generating a credential or starting a child process
