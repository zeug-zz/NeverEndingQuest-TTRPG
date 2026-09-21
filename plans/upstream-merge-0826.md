# Upstream Integration and Selective Merge Plan

**Status:** Open for review and continued updates

**Created:** 2026-08-04

**Last upstream review:** 2026-08-04

**Current upstream review point:** `702796eb55`

**Previous recorded upstream point:** `c149109a64`

**Repository:** `MoonlightByte/NeverEndingQuest`

**Fork:** `zeug-zz/NeverEndingQuest-TTRPG`

## Purpose

This plan defines how NeverEndingQuest-TTRPG should continue reviewing and selectively integrating work from the upstream NeverEndingQuest repository while the upstream developer remains active.

The fork should absorb as much useful upstream work as possible when it is compatible with the fork's architecture. The fork should not preserve upstream behavior merely for the sake of keeping the histories close. TABLETOP MODE markers, extension modules, and isolated adapters exist to make useful upstream changes easier to port, not to require wholesale upstream synchronization.

The fork is also converging toward a separate v2 architecture. As v2 contracts become authoritative, upstream changes that replace or contradict those contracts become reference material rather than merge candidates.

The mission-critical v2 deployment path is now explicit:

1. The facilitator laptop serves the authoritative game and React thin clients over a trusted LAN.
2. The same thin-client contract expands to authenticated clients over the internet.
3. The authoritative Python server later moves from the facilitator laptop to hosted infrastructure in v3 or later.

React is therefore a v2 client foundation, not an optional single-laptop UX experiment. The migration target is a stable client/server boundary that survives all three deployment stages while preserving Python authority.

This document remains open. Each future upstream review should append or update the review ledger, record the new upstream tip, classify new commits, and preserve the rationale for skipped work.

## Executive Policy

1. Do not merge `upstream/main` wholesale.
2. Inspect upstream commits individually, including their parent dependencies and affected files.
3. Prefer a direct cherry-pick only when the commit is isolated, low-conflict, and does not touch TABLETOP authority boundaries.
4. Prefer a manual semantic port when the behavior is useful but the implementation assumes upstream provider, storage, UI, or module-builder architecture.
5. Defer future-v2 work until the corresponding fork-side contract is approved, except for the now-approved React client foundation, which should proceed contract-first.
6. Reject upstream changes that weaken Python mechanical authority, remove fork regression coverage, erase TABLETOP behavior, or replace active fork architecture without a concrete benefit.
7. Never overwrite uncommitted user work, current runtime state, or published fork artifacts while investigating upstream.
8. Keep `upstream` read-only. All commits and pushes remain on the fork's `origin` remote.
9. Record every final decision in the upstream sync log in `AGENTS.md` after implementation, not before the behavior is verified.
10. Keep this plan open until the project explicitly decides that upstream synchronization is no longer a useful maintenance activity.

## Architectural Position

The fork is a TABLETOP MODE extension of upstream, but it is not a permanent downstream patch queue.

Current fork priorities are:

- Local, in-person tabletop operation with one facilitator managing multiple PCs.
- Deterministic Python authority for mechanical state, combat, travel, inventory, party membership, and publication gates.
- Explicit TABLETOP MODE boundaries around upstream host files.
- Isolated extension modules for multi-PC, memory, toolkit, publication, and adaptation behavior.
- GPT-5.6 Luna direct-OpenAI compatibility through the existing provider factory and chat-parameter shim.
- LLM-led adaptation of source adventures into new NEQ-TTRPG modules, with Python-owned validation, staging, publication, registry, and campaign synchronization.
- A future v2 narrative and world-model architecture that will absorb useful legacy semantics without continuing to deepen every legacy subsystem.

### V2 Client Foundation Mission

The fork must support a facilitator-hosted session with multiple browser clients before it moves to internet and hosted-server operation. The client must be replaceable independently of the authoritative game engine.

The intended architecture is:

```text
DM/facilitator laptop or hosted server
    Python game engine + Flask/SocketIO
    Authoritative campaign, party, combat, and persistence state
    Full facilitator interface at /

LAN or internet browsers
    React thin client at /client
    Player-facing state and input only
    No mechanical or publication authority
```

The upstream `/play` implementation is a candidate foundation for the fork's `/client` surface. It should be manually adapted rather than blindly cherry-picked. The legacy HTML interface remains the initial facilitator console at `/` while React client parity is built and verified.

The client foundation must preserve these properties across LAN, internet, and hosted-server stages:

- A versioned client/server event contract.
- Snapshot and reconnect hydration.
- Server-instance and state-revision protection against stale browser state.
- Request IDs and idempotent client actions.
- Shared active-PC synchronization for tabletop play.
- Explicit player-scope, facilitator-scope, and admin-scope event boundaries.
- Authentication and transport hooks that can grow from trusted LAN to internet-safe deployment.
- No dependency on whether the authoritative server is a facilitator laptop or hosted infrastructure.

The fork should continue to preserve single-player compatibility, but single-player compatibility does not justify importing upstream changes that conflict with TABLETOP state authority or the planned v2 boundaries.

## Current Repository Baseline

The 2026-08-04 review found the following local state:

- Current fork `HEAD`: `8d8b540d`, the LLM adaptation-builder planning checkpoint.
- Local `upstream/main` tracking ref: `c3604eb35a`, which is stale relative to the current upstream GitHub `main` branch.
- Current upstream GitHub `main`: `702796eb55`.
- Current fork `main` is four commits ahead of and four commits behind the local `origin/main` tracking ref.
- The worktree contains active uncommitted adaptation-builder and GPT-5.6 build-path work.
- The worktree review reported 116 dirty entries, including 44 modified files and 72 untracked files.
- No upstream commit should be cherry-picked into the current dirty worktree.

The current worktree is user-owned development. It must be checkpointed or isolated in a separate worktree before any upstream patch experiment. It must not be reset, cleaned, stashed destructively, or treated as disposable.

The local ignored `config.py` contains provider configuration and must never be staged, included in diagnostics, or copied into review artifacts. Any provider credential that has escaped the local machine must be rotated.

## Review Window: 2026-08-04

The current upstream window contains 12 commits after the previously recorded `c149109a64` point. The commits form several dependent lanes rather than 12 independent patches.

| Commit | Date | Subject | Decision | Dependency or boundary note |
|---|---|---|---|---|
| `715732d554` | 2026-07-18 | `feat(multi-model): integrate provider-aware game runtime` | Reject as a merge unit; mine concepts only | 112 files and a broad provider/runtime rewrite. It changes core combat, narrator, builders, validation, schemas, startup, storage, and web paths. |
| `f847d1e142` | 2026-07-18 | `fix(security): protect provider credentials and web access` | Port selectively with `9313bf6269` | Contains useful secret storage and web exposure controls, but assumes upstream provider settings and must not be taken alone. |
| `a83db2b9cc` | 2026-07-16 | `feat(frontend): P4 standalone - React/TS player UI at /play` | Adopt manually as the v2 client foundation | Adds the component-based player surface and the initial client-side architecture. Do not replace the facilitator host or import the new build system without a fork-side contract. |
| `b4ab5de946` | 2026-07-18 | `fix(frontend): harden responsive realtime gameplay` | Port selectively with the client foundation | Responsive and realtime behavior is relevant to LAN and internet clients. Port components and tests after the fork event contract is defined. |
| `43a911b983` | 2026-07-18 | `feat(startup): automate React player setup` | Defer installer/default-launcher pieces; port build helpers later | React build preparation is useful, but must be reconciled with the fork's Windows/macOS installers and should not force React for the facilitator host. |
| `be3d0299a8` | 2026-07-18 | `feat(frontend): complete legacy parity and reconnect hardening` | Port selectively with priority on hydration/reconnect | Reconnect and state recovery are foundational for thin clients. The fork already has `request_status` and `status_response`, so only the stronger client contract should be ported. |
| `2bd897a848` | 2026-07-18 | `feat(frontend): match legacy player interface` | Adopt selectively for player parity | Visual and behavioral parity are required for a safe client migration, but the fork must add TABLETOP-specific controls and exclude facilitator/admin surfaces. |
| `f9d155ee70` | 2026-07-19 | `docs(readme): document current startup and providers` | Skip wholesale; port documentation selectively | The fork's installer, tabletop workflow, v2 plans, and provider contract differ. |
| `9313bf6269` | 2026-07-27 | `fix(#129): stop destroying saved provider API keys on startup` | Port with `f847d1e142` | Corrects a durability bug introduced by the earlier secret migration. The pair is one security unit. |
| `665af7e433` | 2026-07-27 | `fix(module-builder): report real failures, accept typed names, retry provider, repair plots` | Port selectively | Directly relevant to the adaptation builder, but its provider errors and module contracts depend on upstream's new API client. |
| `ccfdd31c20` | 2026-07-27 | `chore(tests): stop shipping credential regression tests` | Reject | Removes 144 lines of credential regression coverage. The fork should retain or strengthen equivalent tests. |
| `702796eb55` | 2026-08-03 | `fix(locations): handle T026 capacity failures safely` | Port manually; high priority | Directly relevant to large GPT-5.6 location batches, but depends on upstream's `core.ai.api_client` and strict location implementation. |

### Current Decision Summary

- Direct cherry-picks from this 12-commit window: none recommended.
- Immediate manual ports: security behavior, module-builder failure semantics, location capacity safety.
- Strategic foundation port: React player, typed events, hydration, reconnect, and browser testing.
- Deferred secondary pieces: upstream default UI switching, installer replacement, and host/admin React migration.
- Reject: wholesale provider/runtime rewrite, credential-test deletion, and divergent README replacement.

This is not a decision to stop taking upstream work. It is a decision to take upstream behavior at the correct boundary instead of importing incompatible implementation assumptions.

## Why the Provider Rewrite Is Not a Merge Target

`715732d554` is an architectural rewrite rather than a focused feature commit. It introduces or substantially changes provider routing, response normalization, model configuration, lifecycle handling, module refresh, campaign state, save behavior, combat validation, startup, schemas, and web output.

It also changes or removes areas that the fork has deliberately evolved:

- The fork uses `utils/ai_client_factory.py` and `get_chat_completion_params()` for provider selection and GPT-5.6 request compatibility.
- The fork's active direct-OpenAI contract uses `gpt-5.6-luna`, not the upstream model/configuration matrix.
- The fork retains TABLETOP-specific combat, party, travel, memory, and GUI behavior in files that the upstream commit rewrites.
- The fork's adaptation staging, failure packet, revision, publication, registry, and campaign utilities overlap with the upstream lifecycle and transaction additions.
- The upstream commit removes or replaces LM Studio paths and changes broad runtime behavior that is not part of the fork's current rollout decision.

Useful concepts from the commit may be reviewed individually:

- Provider-neutral error metadata.
- Normalized response contracts.
- Cross-process path locks.
- Atomic JSON cache transactions.
- Explicit module lifecycle states.

These concepts must be compared against existing fork utilities before any new implementation is added. Duplicating an existing adaptation or atomic-write contract is not an acceptable port.

## Workstream A: Security and Network Exposure

### Objective

Port the useful security behavior from `f847d1e142` and the durability correction from `9313bf6269` without importing the upstream provider runtime.

### Required behavior

- Replace the hardcoded Flask signing secret with a random per-process secret or an explicitly configured secret.
- Make web host binding configurable.
- Require an operator token or equivalent authentication when the server is intentionally exposed beyond loopback.
- Restrict SocketIO CORS behavior instead of retaining an unconditional wildcard where the deployment mode does not require it.
- Add security response headers appropriate to the current Flask host.
- Move provider credentials out of plaintext settings when an OS credential store is available.
- Preserve a durable fallback when no OS credential store is available.
- Ensure clearing a credential removes it from every storage location.
- Ensure migrating a credential removes the plaintext copy only after durable storage succeeds.

### Fork-specific decision

The fork currently binds to `0.0.0.0` for trusted-LAN tabletop operation. The upstream default of loopback-only should not be copied without reconciling the v2 remote-client plan.

The implementation should support at least:

- Local-only mode: bind to loopback and require no network token.
- Trusted-LAN mode: bind to an explicit configured interface or LAN host and require an operator/client authentication contract.
- Future internet mode: remain unsupported until TLS, rate limiting, websocket authentication, and deployment-server requirements are separately specified.

The current `plans/version-2/client_network.md` plan should be treated as the source of truth for any `/client` authentication and event-boundary work. The upstream operator token is useful security input but is not automatically the final remote-client design.

### Implementation boundary

Do not port the credential functions into `model_config.py` until the fork has a clear provider-settings persistence surface. If the UI does not currently persist provider keys through `user_settings.json`, first define the storage contract and migration path.

If the keyring approach is adopted:

- Port `secret_store` semantics from the combined upstream pair.
- Preserve the `set_secret()` durability boolean from `9313bf6269`.
- Add an optional or pinned `keyring` dependency only after lockfile and installer impact are reviewed.
- Keep provider values out of logs, reports, failure packets, and OpenSpec artifacts.
- Add provider-free tests for keyring available, keyring unavailable, legacy migration, restart persistence, and clearing.

### Verification

- Flask app startup with loopback defaults.
- Explicit non-loopback startup without a token fails closed.
- Explicit non-loopback startup with a valid token succeeds.
- SocketIO connection behavior matches HTTP authentication behavior.
- Existing local tabletop startup remains functional.
- Provider keys survive restart in both keyring and fallback modes.
- No credential appears in diagnostic output or staged files.
- Security scan, dependency scan, and ASCII compliance pass.

## Workstream B: ModuleBuilder Failure Semantics

### Objective

Port the useful behavior from `665af7e433` into the existing adaptation and toolkit reporting architecture.

### Behaviors to preserve

- A failed build must carry an actionable stage-specific reason instead of returning only `(False, None)` or a generic "module generation failed" message.
- Operator cancellation must be distinct from provider, structural, semantic, and publication failure.
- Provider authentication failures must not be retried as if they were transient transport failures.
- Retryable provider failures may use a bounded retry policy, but must not create a false success artifact.
- Typed operator module names may be normalized before contract validation.
- Model-generated names and adaptation dossier titles must remain subject to their own contract validation rather than being silently normalized into validity.
- Plot reference repair must be bounded, deterministic, and recorded.

### Existing fork overlap

The adaptation lane already contains:

- `toolkit_adaptation_failure_classifier.py`.
- `toolkit_adaptation_failure_packet.py`.
- `toolkit_adaptation_revision.py`.
- Adaptation job reporting and bounded terminal states.
- Staging, registry, campaign, Markdown, and rollback contracts.

The upstream exception taxonomy should be integrated into these contracts rather than creating a parallel generic module-creation error system.

### Proposed port

1. Add or map explicit build exceptions to the adaptation failure classes.
2. Preserve provider stage, provider class, retry count, and operator action guidance.
3. Ensure infrastructure failures do not consume the semantic adaptation revision budget.
4. Normalize operator-supplied module identifiers at the input boundary only.
5. Keep cancellation and failed publication visible in GUI job reporting.
6. Add a safe plot-reference repair stage before final readiness/report agreement.
7. Persist repair diagnostics in the attempt workspace and compact report, not in raw provider output.

### Plot repair safety rule

The upstream repair implementation replaces unknown plot locations by cycling through available locations. That is acceptable only as a narrowly proven fallback and is too broad as a default authority rule for the fork.

The fork should first attempt, in order:

- Exact canonical location match.
- Known area-to-location alias conversion.
- Deterministic normalization of an area ID accidentally used where a location ID is required.
- A bounded LLM revision when the intended location cannot be inferred safely.

Arbitrary replacement by list position should not be used unless the repair is explicitly marked degraded, reviewed by the relevant gate, and covered by a fixture proving the resulting plot remains playable.

### Verification

- Provider failures produce infrastructure status and no semantic revision.
- Authentication failures do not enter the transient retry loop.
- Cancellation produces a non-failure terminal status.
- Invalid operator names are normalized deterministically.
- Model-generated invalid names remain contract failures.
- Plot repairs preserve valid siblings and report every mutation.
- Failed builds leave no registry or campaign side effect.
- Existing accurate-ingest and adaptation suites remain green.

## Workstream C: Location Batch Capacity and Structural Safety

### Objective

Port the safety concepts from `702796eb55` into the fork's current `LocationGenerator`, which already carries adaptation context and the GPT-5.6 chat-parameter helper.

### Required behavior

- Detect explicit provider capacity finish reasons such as `length` or `max_tokens`.
- Detect explicit provider context-window errors without guessing from ordinary content failures.
- Surface a player/operator-safe capacity message that explains the likely remediation.
- Do not save or publish an incomplete location batch.
- Preserve exact location count, stub order, and canonical location IDs.
- Use one bounded full-batch retry for structurally invalid output.
- Use targeted replacement only when the initial batch's count, shape, IDs, and order are trustworthy.
- Verify accepted sibling locations are byte-for-byte or structurally unchanged after targeted repair.
- Perform a final schema/count/order gate before returning the batch.

### Fork-specific implementation

The upstream implementation depends on `core.ai.api_client.ProviderCallError` and upstream provider configuration. The fork should not import that API client solely to take this patch.

Instead:

- Keep `create_chat_client()` and `get_chat_completion_params()` as the request boundary.
- Normalize provider exceptions through the existing factory/error helpers.
- Add a small local capacity classifier if the current factory does not expose enough metadata.
- Preserve `_llm_adaptation_prompt_context` and all current adaptation prompt boundaries.
- Keep the existing JSON response parsing and module schema conventions where they are still valid.
- Reuse existing atomic write utilities and staging boundaries.

### Suggested tests

- Finish reason `length` returns capacity failure.
- Finish reason `max_tokens` returns capacity failure.
- Explicit context-window provider error returns capacity failure.
- Empty non-capacity response receives the ordinary bounded semantic retry.
- First response with invalid one-location payload triggers one full retry.
- Trusted batch with one invalid location triggers targeted replacement.
- Accepted siblings are unchanged after replacement.
- Wrong count, duplicate IDs, reordered IDs, and malformed schema fail closed.
- No area or module file is written from an invalid batch.
- Catalogue adaptation remains free to create a shop/module shape without treating every source item as a location.

## Workstream D: Provider and Runtime Concepts from `715732d554`

This workstream is investigation-only until a concrete fork need is identified.

Potentially reusable concepts include:

- Correlated provider errors with provider, model, and task identity.
- OpenAI-shaped response normalization across providers.
- Cross-process transaction locks.
- Atomic JSON mapping updates.
- Explicit module lifecycle states and recovery status.

Before implementing any of these, compare them against:

- `utils/ai_client_factory.py`.
- GPT-5.6 chat-parameter compatibility helpers.
- Existing atomic JSON and file-operation utilities.
- `utils/toolkit_adaptation_staging.py`.
- `utils/toolkit_adaptation_publication_transaction.py`.
- Existing campaign and registry synchronization code.
- Current OpenSpec contracts.

The expected result is usually one of:

- No action because the fork already has equivalent behavior.
- A small provider-error metadata addition.
- A focused lock or cache test improvement.
- A new v2 OpenSpec change if the concept crosses an architecture boundary.

Do not import the upstream model matrix, upstream model IDs, LM Studio removal, broad combat rewrite, or broad startup rewrite as part of this workstream.

## Workstream E: React V2 Thin-Client Foundation

The previous review treated the upstream React sequence as deferred reference material. That decision is superseded by the v2 deployment mission. NEQ-TTRPG is not single-laptop-only:

1. The facilitator laptop must serve the authoritative game to React thin clients over LAN.
2. The same client contract must support authenticated thin clients over the internet.
3. The authoritative Python server must later be movable to hosted infrastructure without requiring another client rewrite.

React should therefore be adopted as a v2 client foundation, but not as an immediate replacement for the full facilitator interface.

### Target deployment stages

#### Stage E1: Facilitator-hosted LAN play

- The facilitator laptop runs Python, Flask, SocketIO, and the authoritative game loop.
- The existing full interface remains available at `/` for the facilitator.
- React is served at `/client` as a player-facing thin client.
- Multiple browsers receive shared narration, party state, active-PC state, initiative, and relevant character data.
- All player input continues through the existing server validation and game loop.
- The client cannot modify mechanical state directly or access toolkit/admin operations.

#### Stage E2: Authenticated internet thin clients

- React static assets and client events continue using the E1 contract.
- Transport moves from trusted LAN assumptions to HTTPS/WSS or an approved secure tunnel.
- Add client authentication, session handling, rate limiting, origin policy, and websocket authorization.
- Separate facilitator/admin events from player events at the server boundary.
- Preserve reconnect hydration and stale-response protection across higher-latency connections.
- Do not expose the facilitator laptop directly to the public internet without a separately approved deployment and security design.

#### Stage E3: Hosted authoritative server

- Move Flask/SocketIO, campaign state, storage, and background jobs to hosted infrastructure.
- Keep the React client contract stable.
- Replace laptop-local assumptions with durable server storage, campaign isolation, operational logging, and deployment-specific authentication.
- Treat scaling, multi-tenant campaigns, and hosted media as separate v3+ architecture work.

### Why React is the foundation

React is valuable here because it establishes a replaceable client boundary, not because it changes the game engine. The current HTML interface is a large monolith with inline CSS, JavaScript globals, imperative DOM updates, and TABLETOP-specific behavior interleaved with host/admin behavior.

The upstream React work provides useful foundations for:

- Component-owned UI state instead of scattered globals and DOM mutations.
- Derived UI modes for disconnected, starting, play, combat, modal, and input-locked states.
- Typed client/server event contracts.
- Snapshot and reconnect hydration.
- Server-instance IDs, revisions, request IDs, and stale-response guards.
- Component-level and browser-level tests.
- A buildable client bundle that does not ship the full facilitator page to every player.
- Clear separation between player-facing events and toolkit/operator events.

React does not automatically provide a thin network client. The fork must also reduce over-refreshing, narrow event payloads, add capability boundaries, and define authentication. The server remains responsible for Python authority, mechanics, persistence, publication, and campaign state.

### Fork adoption boundary

The fork should use the following division:

```text
DM/facilitator host at /
    Existing legacy interface initially retained.
    Full party management, toolkit, debug, save/load/reset, and shutdown controls.

React player client at /client
    Transcript, player input, active-PC selection, relevant sheets, party state,
    initiative, combat-facing state, and player-safe dialogs only.

Shared Python/Flask/SocketIO server
    Mechanical authority, state transitions, validation, persistence, and events.
```

Upstream's `/play` route and React code are a starting point, not the fork's final route or capability set. The fork must not blindly carry over upstream provider settings, save/reset scope, local-edition controls, or default UI switching.

### React foundation implementation phases

#### E0: Freeze the fork client contract

Define and test the fork-native contract before importing the upstream component tree:

- Client-to-server and server-to-client event names.
- Exact SocketIO payload arity.
- Shared, sender-only, facilitator-only, and admin-only event classes.
- `party_members` versus `members` payload conventions.
- Fork portrait slug/version fields.
- Active-PC synchronization semantics.
- Request IDs, state revisions, server-instance IDs, and snapshot hydration.
- Authentication/session metadata.
- Compatibility behavior for single-player and TABLETOP modes.

This contract is the first real React port. It is more important than copying the upstream JSX.

#### E1: Vendor the minimum React shell

- Add the React build under a fork-owned `web/frontend` boundary.
- Serve it at `/client` without changing `/`.
- Start with upstream stores, socket service, hydration coordinator, UI mode state, and contract organization.
- Exclude toolkit, party-management, PC-edit, debug, and shutdown operations from the client bundle.
- Keep React build failure fail-open to the legacy facilitator host, but make an explicitly requested client build failure visible to the operator.

#### E2: Add TABLETOP client parity

Port only the player-facing fork behavior required for LAN play:

- Shared PC tabs and active-character selection.
- Multi-PC initiative and combat state rendering.
- Read-only character sheet and relevant inventory/spell information.
- Player input and prefill behavior.
- `[skipTTS]` and narration output handling.
- Portrait slug/version and media fallback behavior.
- Connection, processing, combat, and input-lock states.
- Reconnect snapshot and stale response protection.

Keep PC creation, editing, promotion, party management, toolkit, MMG, readiness repair, and facilitator controls on `/` until their security and authorization boundaries are separately designed.

#### E3: Prove LAN operation

- Run one facilitator host with two or more browser clients.
- Verify all clients see the same user echo and narration timeline.
- Verify active-PC selection behavior is explicit and consistent.
- Verify initiative and combat state remain synchronized.
- Verify a client refresh or reconnect hydrates current state without replaying stale messages.
- Verify a client cannot reach facilitator-only routes or shutdown behavior.

#### E4: Harden for internet thin clients

- Add HTTPS/WSS or an approved tunnel architecture.
- Add authentication and websocket authorization.
- Add rate limits and connection limits.
- Restrict CORS/origins by deployment mode.
- Separate public client events from facilitator/admin events.
- Test latency, reconnect, duplicate submissions, and stale snapshots.

#### E5: Prepare hosted-server migration

- Remove assumptions that the server shares a filesystem with the browser.
- Identify campaign, module, media, and session storage boundaries.
- Define server deployment and process supervision requirements.
- Preserve the React client contract while changing only the server endpoint and deployment environment.

### What remains deferred within the React lane

These parts of the upstream sequence are not foundational and should be ported only after E0 through E3 are stable:

- Upstream default launcher changes.
- Installer replacement or mandatory Node.js installation.
- Full React replacement of the facilitator host interface.
- React toolkit/operator surfaces.
- Public internet exposure without the security work in E4.
- Visual parity work that does not improve client correctness or tabletop usability.

### React verification requirements

- Provider-free TypeScript/component tests for stores, hydration, event arity, and UI modes.
- Playwright LAN smoke coverage with one host and multiple clients.
- Reconnect and stale-response tests.
- Active-PC and initiative synchronization tests.
- Client route isolation tests.
- Existing Python tabletop and single-player suites remain green.
- No regression in the legacy facilitator interface while `/client` is introduced.

The React lane is now an active v2 foundation, not a permanently deferred experiment. It remains a manual port because upstream and fork event payloads, TABLETOP behavior, provider settings, and host routes differ.

## Cherry-Pick and Manual-Port Procedure

### Before applying any upstream commit

1. Confirm the current worktree is clean or work in a separate temporary worktree.
2. Confirm the commit's parent chain and whether its prerequisites are already present.
3. Inspect the full file list and identify TABLETOP-sensitive files.
4. Read the commit message, diff, tests, and follow-up fixes.
5. Check whether the commit changes provider IDs, request parameters, schemas, runtime file paths, or installer behavior.
6. Determine whether the behavior is already covered by a fork-side implementation.
7. Choose direct cherry-pick, selective patch, deferred reference, or rejection.

### Direct cherry-pick criteria

A direct cherry-pick is allowed only when all conditions hold:

- The commit has a narrow purpose.
- It does not touch TABLETOP-sensitive host files, or its changes are demonstrably independent.
- It does not assume an upstream-only module, provider, schema, or file layout.
- Its tests are compatible with the fork's test layout.
- It does not remove existing fork coverage.
- It does not modify runtime state or published module artifacts unexpectedly.
- It can be reverted without undoing unrelated fork work.

### Selective manual-port criteria

Use a manual port when:

- The behavior is useful but the files are heavily divergent.
- The commit depends on upstream provider infrastructure.
- The commit changes a host file containing TABLETOP hooks.
- The fork has a stronger or newer equivalent contract.
- The behavior must be expressed through an existing adaptation or v2 boundary.

Manual ports must preserve the upstream intent while using fork-native helpers, schemas, logging, tests, and publication boundaries.

### Required port record

Each implemented port should record:

- Upstream commit hash and subject.
- Files or behavior ported.
- Files intentionally not ported.
- Fork-native replacement used for any upstream dependency.
- TABLETOP MODE markers added or preserved.
- Tests added or updated.
- Verification commands and results.
- Any behavior intentionally changed for the fork.
- Rollback instructions.

## Validation Gates

Every accepted upstream port must pass the smallest relevant gates before broader testing.

### Code and contract gates

- `.venv/bin/python -m py_compile` for modified Python files.
- Provider-free focused tests for the port.
- Existing TABLETOP regression suites for touched runtime domains.
- OpenSpec validation for changes crossing a contract boundary.
- ASCII compliance for new or modified source and prompt files.
- `git diff --check`.

### Runtime and publication gates

- No invalid JSON or partial module batch is persisted.
- No failed build registers a module or updates the active campaign.
- No runtime state is staged as canonical module content.
- No provider credential or raw source material appears in diagnostics.
- Existing single-player behavior remains smoke-testable.
- TABLETOP multi-PC behavior remains smoke-testable.

### Provider gates

- Request-shape tests capture final kwargs without a live provider.
- GPT-5.6 Luna paths omit unsupported legacy parameters.
- OpenRouter request shape remains unchanged unless a separate decision approves it.
- Provider outage, quota, timeout, authentication, refusal, and capacity failures remain distinguishable.
- Live provider tests are bounded, use minimal fixtures, and do not persist secrets or raw provider responses.

## Upstream Tracking Cadence

This plan should be revisited whenever any of the following occurs:

- Upstream adds more than a few commits to `main`.
- Upstream changes provider, web, module-builder, startup, or storage architecture.
- A fork bug appears likely to have an upstream fix.
- A v2 plan reaches an implementation decision that changes the merge boundary.
- A release or tester handoff is being prepared.

### Review procedure for future upstream changes

1. Refresh local remote refs in an isolated worktree.
2. Record the previous reviewed commit and new upstream tip.
3. List commits in the new range.
4. Group commits by dependency lane.
5. Inspect each commit independently.
6. Re-check parent/follow-up fixes before accepting an early commit.
7. Update the decision ledger in this file.
8. Create OpenSpec work only for accepted implementation lanes.
9. Update `AGENTS.md` after verification.
10. Leave deferred and rejected decisions recorded for future reference.

### Review ledger template

Use this template for each future upstream window:

```text
## Upstream Review: YYYY-MM-DD

- Local upstream ref before refresh:
- Upstream tip reviewed:
- Previous reviewed upstream commit:
- New commit count:
- Worktree status:
- Origin status:

| Commit | Subject | Classification | Action | Dependencies | Verification |
|---|---|---|---|---|---|
| `<sha>` | `<subject>` | `port/cherry-pick/defer/reject` | `<summary>` | `<parents or follow-ups>` | `<commands or pending>` |

### Review conclusion

<Explain which work is worth porting and why.>

### Open follow-up

<List accepted ports, deferred v2 work, and unresolved questions.>
```

## V2 Divergence Rules

The fork is allowed to diverge more as v2 contracts mature. The following rules determine when an upstream merge stops being useful:

### Continue taking upstream work when

- It fixes a security issue or data-loss bug without replacing fork authority.
- It fixes a provider compatibility issue that can be expressed through the fork factory.
- It improves a focused generator or validator boundary without changing source-of-truth semantics.
- It improves cross-platform installer or runtime reliability without replacing the fork's installer contract.
- It adds tests or observability that can be mapped into the fork's test layout.
- It strengthens the React client/server boundary needed for LAN play, authenticated internet clients, or later hosted-server migration.

### Prefer manual porting when

- Upstream and fork touch the same core files.
- Upstream changes a provider abstraction or model configuration.
- Upstream changes module publication, registry, campaign, or staging semantics.
- Upstream changes the web host, SocketIO, reconnect, or client event contract.
- Upstream changes a prompt or schema that has TABLETOP-specific parity requirements.

### Defer when

- The feature belongs to a future v2 memory, world-model, Titan, or adaptation contract that has not yet reached implementation.
- The fork has not approved the corresponding OpenSpec boundary.
- The upstream implementation is still visibly changing direction and the behavior is not required for the client foundation.
- Adopting it would add a second parallel runtime path without a migration plan.

React client work is not deferred merely because it belongs to v2. It is deferred only when the specific piece is outside the current client foundation, such as installer replacement, default UI switching, or host/admin migration.

### Reject when

- It removes fork regression tests or weakens fail-closed behavior.
- It makes the LLM authoritative over mechanical or publication state.
- It writes directly to live registry, campaign, or runtime state without the fork's transaction gates.
- It assumes upstream data structures that conflict with shared party or combat state.
- It replaces a stable fork implementation with a broad rewrite solely to reduce diff divergence.

## Proposed Implementation Order

The following order minimizes rework:

1. Preserve and checkpoint the current adaptation worktree.
2. Reconcile the fork's `origin/main` relationship separately from upstream review.
3. Create the upstream decision ledger entry for the 12-commit window.
4. Freeze the fork-native React client/server event and authentication contract.
5. Implement the security pair and network-mode decisions needed for LAN clients.
6. Add the minimum React client shell at `/client` while preserving the legacy facilitator host at `/`.
7. Prove multi-browser LAN gameplay, reconnect hydration, active-PC synchronization, and client route isolation.
8. Finish GPT-5.6 build-path compatibility verification.
9. Port module-builder failure semantics into adaptation reporting.
10. Port location capacity and structural batch safety.
11. Harden the client boundary for internet operation before any public exposure.
12. Define the hosted-server migration separately for v3 or later.
13. Re-run adaptation, publication, tabletop, and browser regression suites.
14. Re-review upstream after the next active development window.

No step should use a wholesale upstream merge as a shortcut.

## Decisions Requested for Review

Please review and confirm the following before implementation begins:

1. Approve React as the v2 thin-client foundation for LAN, internet, and later hosted-server stages.
2. Approve keeping the legacy interface at `/` as the initial facilitator/DM host while React is introduced at `/client`.
3. Approve the fork-native event, hydration, authentication, and capability contract as the first React implementation task.
4. Approve the combined `f847d1e142` and `9313bf6269` security port as the first supporting infrastructure lane.
5. Approve manual porting of `665af7e433` and `702796eb55` into the adaptation builder rather than importing upstream `core.ai.api_client`.
6. Defer only the React installer replacement, default UI switch, host/admin migration, and internet exposure until their prerequisites are verified.
7. Preserve the rule that no current-window commit is directly cherry-picked without a clean dependency and TABLETOP-impact review.
8. Continue maintaining this plan as an open upstream review ledger.

## Related Documents

- `AGENTS.md`, especially ADR-0030 and the upstream sync log.
- `plans/adaptation-builder.md`.
- `plans/version-2/client_network.md`.
- `plans/version-2/client-web.md`.
- `plans/version-2/openrouter_llm_router_architecture.md`.
- `openspec/changes/toolkit-gpt5-build-path-compatibility/`.
- `openspec/changes/toolkit-llm-adaptation-builder/`.
- `utils/ai_client_factory.py`.
- `utils/toolkit_adaptation_failure_classifier.py`.
- `utils/toolkit_adaptation_publication_transaction.py`.

## Current Status

This plan is ready for review. No upstream code has been merged or ported as part of this document update.
