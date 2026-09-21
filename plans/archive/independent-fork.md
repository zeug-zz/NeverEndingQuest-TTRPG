# Independent Development Fork Implementation Plan

**Status:** Approved and complete; implementation tracked by OpenSpec changes `fork-independence-pivot` (governance) and `fork-final-upstream-sweep` (behavior ports), both archived on 2026-09-21; this plan is archived at `plans/archive/independent-fork.md`
**Created:** 2026-09-21
**Owner:** NeverEndingQuest-TTRPG maintainers
**Scope:** Repository governance, upstream separation, and final selective behavior ports

## Executive Decision

NeverEndingQuest-TTRPG will become an independently developed TTRPG platform that was
originally derived from MoonlightByte/NeverEndingQuest. Upstream will remain a historical
and technical reference only. The repository will no longer maintain merge-safe parity,
routine upstream review, or a downstream patch-porting queue.

The fork will retain useful internal engineering boundaries:

- Python remains authoritative for mechanical, persistence, publication, and campaign state.
- Extension boundaries remain useful for testability and ownership, but no longer exist to
  minimize upstream merge conflicts.
- `# TABLETOP MODE:` markers remain as lineage and ownership documentation.
- Single-player compatibility remains an internal product requirement.
- The Fair Source license, upstream copyright headers, and required attribution remain intact.

The implementation has two active workstreams:

1. Record the independent-fork decision in ADRs, OpenSpec guidance, repository guidance,
   README text, and the closing upstream review plan.
2. Complete a small final sweep of portable upstream behavior: legacy UI output escaping and
   bounded recovery from transient empty provider responses.

The upstream React client remains a future, one-time vendor seed for the fork's `/client`
surface. It is not part of the governance pivot or final behavior sweep.

## Locked Decisions

The following decisions were approved before this plan was written:

| Decision | Locked outcome |
|---|---|
| Development relationship | Independent fork; upstream is historical reference only |
| Final upstream sweep | Port the legacy UI security pattern and provider empty-response retry; inspect upstream #240 and port only if the same bug exists |
| React client | Vendor the upstream React snapshot as a one-time seed, then fork it with no ongoing sync |
| Git remote | Keep `upstream` read-only and stop routine fetching; all pushes remain explicit to `origin` |
| ADR strategy | Add ADR-0031; supersede ADR-0030 and ADR-0002; rescope ADR-0003 |
| TABLETOP MODE markers | Keep existing markers as lineage documentation; remove merge-boundary meaning |

## Evidence And Baseline

The previous upstream plan is archived at `plans/archive/upstream-merge-0826.md`. Its stated exit condition is
to remain open until upstream synchronization is no longer useful. That condition is now
met.

### Repository divergence

The repository review on 2026-09-21 found:

- Fork merge base: `c3604eb35a` from 2026-02-19.
- Fork `HEAD`: `c4b16311`.
- Fork `HEAD` is 393 commits ahead of the local upstream merge base.
- Upstream `main`: `44f1458e1e` from 2026-09-20.
- Upstream is 537 commits ahead of the same merge base.
- The review window after the previous plan point `702796eb55` contains 524 upstream
  commits from 2026-08-05 through 2026-09-20.
- The worktree was clean at plan creation.
- The fork was one commit ahead of `origin/main`; `c4b16311` must be pushed separately when
  the maintainer authorizes the push.

### Architectural divergence

The upstream review window introduced or expanded these upstream-owned directions:

- Typed model registries and task-specific model routing.
- Agentic combat and referee workflows.
- NPC voice generation and episodic NPC memory.
- Headless transport and Responses API lifecycle handling.
- Provider liveness, transport keepalive, and startup lifecycle recovery.
- Crash-safe transaction coordination and upstream module publication flows.
- Specialist level-up interviews and prepared-sheet workflows.
- New desktop and React player surfaces.

The fork instead owns:

- Deterministic Python authority for multi-PC tabletop play.
- Multi-PC combat phase and roster contracts.
- Reconcile-first travel, NPC presence, inventory, and character state guards.
- Two-plane memory, companion relationship memory, diary, and story export behavior.
- Accurate-ingest, adaptation, staging, readiness, semantic, media, and publication gates.
- Direct OpenAI GPT-5.6 Luna routing through `utils/ai_client_factory.py`.
- A legacy facilitator host with a planned fork-owned `/client` boundary.

These are no longer compatible implementation paths. A wholesale merge would create a
second authority model and replace tested fork contracts with upstream assumptions.

## Objectives

The implementation MUST:

1. Make independent fork governance the canonical repository policy.
2. Preserve useful internal architecture discipline without treating upstream parity as a
   design constraint.
3. Explicitly classify the remaining upstream candidates as port, inspect-only, or leave
   behind.
4. Port only behavior that is narrow, independently testable, and relevant to the fork.
5. Preserve both single-player and TABLETOP MODE behavior.
6. Preserve the fork's Python mechanical and publication authority.
7. Keep the implementation reversible and free of saved-game or module-data migrations.
8. Leave a durable record explaining why the 2026 upstream development branch was not merged.

## Non-Goals

This plan MUST NOT:

- Merge `upstream/main` or cherry-pick the upstream development branch wholesale.
- Import the upstream provider registry, Responses API, agentic combat runtime, or NPC voice
  architecture.
- Replace the legacy facilitator interface at `/`.
- Rename all existing `# TABLETOP MODE:` markers.
- Remove upstream attribution, copyright headers, or the repository license.
- Modify runtime campaign state, module artifacts, character files, or saved games.
- Make the React `/client` surface part of the governance pivot implementation.
- Add a routine upstream review or synchronization cadence after this plan is complete.

## Upstream Candidate Classification

### Port in the final sweep

#### Legacy UI literal-text and attribute encoding

**Reference:** upstream PR #399, merge commit `2940c9f0`.

The upstream change adds `escapeLegacyHtml()` and `legacyJsonAttribute()` patterns for
legacy panels, tooltips, saved-game actions, NPC actions, and character/item text. The fork
has approximately 64 `innerHTML` sites in `web/templates/game_interface.html` and several
inline handlers interpolating names directly, including:

- `openReadinessRepairModal('${normalizedName}')`
- `uploadPortrait('${normalizedName}')`
- `createPortrait('${normalizedName}')`
- `downloadPortrait('${normalizedName}')`
- `openCharacterEdit('${normalizedName}')`
- NPC save and skill handlers using `npc.name`

The fork MUST port the safety behavior manually rather than cherry-picking the upstream
template diff. The template has diverged substantially, and the fork's existing portrait
slug and tabletop behavior must remain unchanged.

#### Transient empty provider response recovery

**Reference:** upstream commits `3fa138f7` and the associated #161/#162 work.

The fork's provider factory handles retryable exceptions and provider fallback, but no
shared path currently classifies an empty completion as a transient provider failure. A
provider response with no choices or empty content MUST NOT silently become a successful
empty turn.

The fork MUST implement bounded retry and existing fallback behavior using fork-native
helpers. `create_chat_client()` MUST remain a client-construction function; request retry
logic MUST NOT be hidden inside client construction.

### Inspect, then port only if duplicated in the fork

#### Completed provider-error reissue

**Reference:** upstream `3e6dbb6f`, associated with issue #240.

Perform a bounded code review of the fork's provider error and fallback state. If the fork
already prevents completed errors from being reissued, record the result and do nothing.
If the same bug exists, add the smallest fork-native fix and extend the provider-free tests.

### Leave behind

The following upstream work is explicitly not a merge target:

- Typed model registry and upstream model matrix.
- Agentic combat, referee, and typed combat state replacement.
- NPC voice and episodic memory architecture.
- Responses API input-item migration and upstream transport lifecycle.
- TCP keepalive and upstream provider-liveness orchestration.
- Upstream crash-safe transaction coordinator and lifecycle registry.
- Upstream startup, installer, launcher, and headless host rewrites.
- Upstream atomic module publication implementation.
- Upstream level-up specialist interview implementation.
- Ember desktop UI and upstream facilitator UI redesign.
- Upstream React implementation as an ongoing synchronization target.
- Upstream #401 React CSS URL patch unless the same code is later vendored into `/client`.
- Upstream #665af7e433 module-builder implementation assumptions.
- Upstream `702796eb55` location-capacity implementation assumptions.

The behavioral goals behind builder failure reporting and location capacity safety remain
valid fork-native backlog items. They MUST be designed against the fork's adaptation and
`LocationGenerator` contracts, not imported from upstream.

## Workstream A: Independent Fork Governance

### A1. ADR-0031

Create `adrs/0031-independent-development-fork.md` with:

- Status: `Accepted` after implementation review.
- Supersedes: ADR-0002 and ADR-0030.
- Relationship to ADR-0003: rescope the internal extension discipline; upstream-first
  behavior is no longer required.
- Context: the fork has diverged by hundreds of commits and now owns different state,
  provider, UI, memory, combat, and publication architectures.
- Decision: develop independently; treat upstream as historical reference; port behavior
  only through separately approved fork changes.
- Internal boundaries that remain: Python authority, atomic state writes, SP/MP support,
  extension boundaries, testable contracts, and ASCII source policy.
- Remote policy: keep `upstream` read-only; do not fetch as routine maintenance; never push
  to upstream.
- Attribution and license policy: preserve Fair Source terms, upstream copyright notices,
  and third-party attribution for any vendored code.
- React policy: a future upstream React snapshot may be vendored once as a fork-owned seed;
  it will not create a synchronization obligation.
- Marker policy: `# TABLETOP MODE:` identifies fork-owned lineage and integration points;
  it does not promise merge compatibility.

### A2. Existing ADR status updates

Update the metadata and consequence sections as follows:

- `adrs/0002-merge-safe-tabletop-overlay-architecture.md`
  - Set status to `Superseded`.
  - Set `Superseded by: ADR-0031`.
  - Preserve the historical rationale and the note that a TT-only fork was a future
    extraction path.
- `adrs/0003-upstream-first-extend-do-not-replace-policy.md`
  - Set status to `Amended` or the repository's accepted equivalent.
  - State that extension-first design remains an internal maintainability rule, while
    upstream-first preservation and merge parity are retired.
  - Link to ADR-0031.
- `adrs/0030-fork-divergence-upstream-as-patch-source.md`
  - Set status to `Superseded`.
  - Set `Superseded by: ADR-0031`.
  - Preserve its patch review history as historical context.
- `adrs/index.md`
  - Add ADR-0031.
  - Update the status descriptions and supersession map.

### A3. OpenSpec guidance

Update `openspec/config.yaml` so its project context no longer calls the repository a
merge-safe upstream plugin and no longer requires preserving upstream structure. Retain:

- Python state as ground truth.
- Atomic JSON operations.
- ASCII-only source and user-facing output.
- SP/MP compatibility.
- Contract-layer MUST requirements and guidance-layer SHOULD recommendations.

Replace upstream-oriented guidance with:

- Prefer local extension boundaries when they improve ownership or testing.
- Do not preserve an upstream implementation unless a fork requirement explicitly needs it.
- Mark host changes when the marker communicates fork ownership or authority boundaries.
- Evaluate external code as a reference and port only through an approved contract.

### A4. Repository guidance and README

Update `AGENTS.md`:

- Reframe the project overview as an independent tabletop platform originally derived from
  upstream.
- Remove the active ADR-0030 upstream sync policy.
- Remove the active Upstream Sync Log requirement.
- Remove the legacy upstream merge guidelines as an operational policy.
- Add a short Fork Independence Policy pointing to ADR-0031.
- Keep origin-only push safety rules.
- State that the upstream remote is inert/read-only and is not part of routine development.
- Keep `# TABLETOP MODE:` markers as lineage documentation, not merge boundaries.
- Preserve all existing security, state authority, publication, and module contracts.

Update `README.md`:

- Replace "Built as a merge-safe plugin on top of upstream" with independent-fork wording.
- Keep the original upstream link and fork link for attribution and provenance.
- Do not imply compatibility with upstream's current runtime or development branch.

### A5. Close the old upstream plan

Move `plans/upstream-merge-0826.md` to `plans/archive/upstream-merge-0826.md` only after
the final sweep is complete. Add a final review ledger before moving it:

- Review date: 2026-09-21.
- Previous review point: `702796eb55`.
- Current upstream tip: `44f1458e1e`.
- New review window: 524 commits.
- Final decisions: #399 and #161/#162 ported; #240 inspected; remaining upstream work left
  behind.
- Reason: upstream and fork now have incompatible architecture and authority boundaries.
- Replacement policy: ADR-0031 and this plan.

Completed 2026-09-21: the ledger was recorded in the plan, which was then archived at
`plans/archive/upstream-merge-0826.md`.

## Workstream B: Legacy UI Output Safety Port

### B1. Scope

Modify `web/templates/game_interface.html` only through a manual, fork-aware adaptation of
the upstream #399 behavior. Do not copy the upstream template wholesale.

The port MUST cover:

- Text inserted into `innerHTML`.
- Text inserted into HTML attributes.
- Names and identifiers passed to inline event handlers.
- Tooltip and saved-game descriptions.
- NPC, character, item, quest, spell, and portrait display values.

The port SHOULD reduce raw inline handler interpolation where practical, but a broad
template JavaScript rewrite is out of scope.

### B2. Implementation shape

Add small, local helpers with explicit context:

- `escapeLegacyHtml(value)` for text and attribute fragments.
- `legacyJsonAttribute(value)` for serialized data embedded in HTML attributes.

The helpers MUST:

- Handle `null`, `undefined`, numbers, and strings safely.
- Escape HTML-significant characters before insertion into HTML.
- Preserve visible text exactly for ordinary game content.
- Avoid double encoding when the value is already serialized by the helper.
- Never expose raw character or NPC names as executable JavaScript.

Use `JSON.stringify` plus HTML attribute escaping for structured handler data. Preserve
existing normalized slugs for routing and media lookup; escaping is not a substitute for
canonical identity normalization.

### B3. Tests

Add a provider-free source-contract suite, for example:

- `scripts/test_legacy_ui_output_safety.py`

The suite MUST verify:

- Both helpers exist and are used in the intended template scope.
- Adversarial values containing quotes, angle brackets, ampersands, backticks, and event
  handler text are escaped.
- Ordinary names remain readable.
- Inline handler arguments are serialized safely.
- Existing `# TABLETOP MODE:` behavior and portrait slug handling remain present.

Run the existing `neq-playwright-smoke` skill or an equivalent targeted browser check with
adversarial display names when the local browser environment is available.

## Workstream C: Empty Provider Response Recovery

### C1. Scope

Add fork-native recovery for transient empty chat completions without importing upstream's
provider runtime or Responses API.

Relevant existing boundary:

- `utils/ai_client_factory.py` constructs provider clients and resolves model parameters.
- Existing call sites issue Chat Completions requests directly.
- Existing fallback logic classifies provider exceptions but does not classify empty results.

The implementation MUST keep client construction separate from request execution. A shared
response/retry helper MAY be added if it avoids duplicating logic across call sites.

### C2. Required behavior

An empty completion includes at least:

- A response with no `choices`.
- A response whose selected choice has no usable message content.
- A response with a blank content string where the caller requires a textual response.

The runtime MUST:

1. Classify the result as transient rather than successful output.
2. Retry no more than the approved bounded count.
3. Preserve the existing request parameters and GPT-5.6 Luna compatibility rules.
4. Use existing provider fallback behavior after the bounded retry is exhausted when the
   provider error policy permits fallback.
5. Surface a deterministic failure when no usable response is available.
6. Avoid persisting an empty assistant turn, empty action envelope, or false success artifact.

The runtime MUST NOT treat refusal, content-filter, authentication, quota, or explicit
invalid-request responses as empty transient responses. Those classes retain their existing
handling.

### C3. Tests

Add provider-free coverage, for example:

- `scripts/test_provider_empty_response_retry.py`

The suite MUST cover:

- Empty response followed by valid response.
- Empty response through the retry bound.
- Empty response followed by provider fallback.
- No retry for refusal or authentication errors.
- No empty action or narration persisted after terminal failure.
- Existing GPT-5.6 request parameters remain unchanged.
- Existing OpenRouter request-shape tests remain green.

Run the relevant GPT-5.6, provider routing, retry hygiene, and narrator/combat regression
suites with `.venv/bin/python`.

## Workstream D: React Client Seed, Deferred

This workstream is approved in principle but is not part of the independent-fork pivot
implementation.

### D1. Future change boundary

Create a separate future OpenSpec change, tentatively named
`v2-client-foundation-independent-seed`.

The change will vendor the upstream `web/frontend` snapshot once, retain its license and
attribution, and immediately adapt it to a fork-owned contract. It MUST NOT establish
ongoing upstream synchronization.

### D2. Future requirements

The future client change MUST:

- Serve the player client at `/client` without replacing `/`.
- Define fork-native event names, payload arity, request IDs, revisions, and snapshot
  hydration before broad component migration.
- Preserve Python authority over mechanics, persistence, publication, and campaign state.
- Exclude facilitator, toolkit, debug, party-management, and shutdown controls from the
  player bundle.
- Preserve LAN-first operation and leave internet exposure behind a separate security gate.
- Re-run the upstream #401 CSS URL safety check against the vendored fork code.
- Use provider-free TypeScript/component tests and Playwright multi-client smoke tests.

## OpenSpec Outline 1: `fork-independence-pivot`

This change records the governance decision and updates all active repository guidance. It
does not modify gameplay runtime behavior.

### `proposal.md` outline

```text
## Why

The fork and upstream now have incompatible runtime, state-authority, provider, UI, memory,
combat, and publication architectures. Maintaining merge-safe downstream behavior creates
cost without preserving useful compatibility.

## Objective

Make NeverEndingQuest-TTRPG an independent development fork while retaining attribution,
internal architecture discipline, and a small approved final behavior sweep handled by a
separate implementation change.

## What Changes

- Add ADR-0031.
- Supersede ADR-0002 and ADR-0030.
- Rescope ADR-0003.
- Update OpenSpec context and repository guidance.
- Replace README merge-safe wording.
- Close and archive the upstream merge plan after the final sweep.

## Non-Goals

- No wholesale upstream merge.
- No runtime provider, combat, memory, or UI replacement.
- No module or saved-game migration.
- No removal of attribution or license requirements.
- No React implementation in this change.

## Rollout And Fallback

Documentation-only behavior. Revert the documentation commit if review rejects the policy;
no gameplay state or runtime data is changed.
```

### `design.md` outline

```text
## Architecture Boundary

The fork owns its runtime contracts. Upstream is reference material only.

## ADR Transition

ADR-0031 supersedes ADR-0002 and ADR-0030. ADR-0003 is amended to retain internal
extension-first discipline without upstream-first compatibility requirements.

## Documentation Synchronization

Update ADR index, AGENTS.md, README.md, openspec/config.yaml, and the archived upstream plan.

## Marker And Remote Policy

TABLETOP MODE markers identify lineage and authority boundaries. The upstream remote remains
read-only and is not fetched routinely.

## License And Attribution

Retain Fair Source terms, upstream copyright notices, and attribution for vendored code.

## Rollback

Documentation changes are isolated and revertible. No runtime migration is needed.
```

### `specs/` outline

Proposed capability specs:

- `independent-fork-governance`
- `fork-adr-supersession-record`
- `fork-documentation-source-of-truth`
- `fork-upstream-reference-policy`

Normative requirements should include:

1. The repository MUST identify itself as independently developed.
2. ADR-0031 MUST be discoverable from the ADR index and MUST identify its superseded ADRs.
3. Active guidance MUST NOT require routine upstream synchronization or merge parity.
4. The upstream remote MUST remain non-pushable.
5. Existing attribution, license, and copyright obligations MUST remain present.
6. TABLETOP MODE markers MUST be treated as lineage documentation rather than merge
   compatibility guarantees.
7. The change MUST NOT modify runtime campaign, module, character, or save state.

### `tasks.md` outline

- [ ] Record the clean baseline, fork point, upstream tip, and current origin relationship.
- [ ] Write ADR-0031.
- [ ] Mark ADR-0002 superseded and preserve its historical rationale.
- [ ] Rescope ADR-0003.
- [ ] Mark ADR-0030 superseded and preserve its review history.
- [ ] Update `adrs/index.md` and supersession map.
- [ ] Update `openspec/config.yaml` context and guardrails.
- [ ] Update active upstream references in `AGENTS.md`.
- [ ] Update README fork relationship wording.
- [ ] Add the final review ledger to `plans/upstream-merge-0826.md`.
- [ ] Archive the old upstream plan after the final sweep.
- [ ] Run documentation, ASCII, OpenSpec, and stale-reference verification.

## OpenSpec Outline 2: `fork-final-upstream-sweep`

This change contains the two approved behavior ports and the bounded inspection of upstream
#240. It MUST be implemented after or alongside the governance change, but it MUST not use a
wholesale cherry-pick.

### `proposal.md` outline

```text
## Why

Only a small number of upstream behaviors remain portable. The fork has a legacy UI output
encoding gap and no shared empty-provider-response recovery, while upstream's surrounding
implementations are incompatible with the fork.

## Objective

Port the security-relevant legacy UI encoding pattern and bounded empty provider response
recovery using fork-native code, tests, and contracts.

## What Changes

- Add legacy HTML and attribute encoding helpers and apply them to high-risk output paths.
- Add bounded transient empty-response recovery at the fork provider boundary.
- Inspect upstream #240 and port only if the fork reproduces the defect.

## Non-Goals

- No upstream cherry-pick.
- No Responses API migration.
- No provider registry or model matrix adoption.
- No combat, memory, startup, module-builder, or React replacement.

## Rollout And Fallback

Ports are additive and provider-free tested. Revert each port independently if a focused
regression appears. Empty-response recovery MUST fail closed rather than persist empty output.
```

### `design.md` outline

```text
## Legacy UI Safety Boundary

Use explicit HTML text, HTML attribute, and JSON-in-attribute contexts. Preserve canonical
slug normalization separately from escaping. Apply the smallest safe set of call-site edits.

## Provider Response Boundary

Keep create_chat_client() responsible for client construction. Place response classification
and bounded retry in a shared request/response helper or the smallest common call boundary.
Preserve GPT-5.6 Luna and OpenRouter request-shape behavior.

## Failure Classes

Distinguish empty transient responses from refusal, content filtering, authentication, quota,
timeout, and invalid request failures.

## Observability

Record bounded retry and terminal empty-response outcomes without provider credentials or raw
provider payloads.

## Rollback

Keep the UI helpers/call-site changes and provider retry helper independently revertible.
No persistence or schema migration is allowed.
```

### `specs/` outline

Proposed capability specs:

- `legacy-ui-literal-output-safety`
- `legacy-ui-handler-argument-safety`
- `provider-empty-response-recovery`
- `provider-response-failure-classification`

Normative requirements should include:

1. User-controlled or authored display values MUST be escaped before HTML insertion.
2. Structured inline-handler arguments MUST be serialized and HTML-attribute escaped.
3. Ordinary character, NPC, item, quest, spell, and save text MUST remain visibly unchanged.
4. Empty provider completions MUST be classified as non-success results.
5. Empty completions MUST retry only within a bounded limit.
6. Terminal empty completions MUST NOT create empty narration, action, or success artifacts.
7. Refusal, content-filter, authentication, quota, and invalid-request errors MUST retain
   their existing classifications.
8. GPT-5.6 Luna and OpenRouter request-shape contracts MUST remain unchanged.
9. Both single-player and TABLETOP MODE MUST retain their existing routing behavior.

### `tasks.md` outline

- [ ] Capture upstream #399 and #161/#162 references in the change record.
- [ ] Audit current legacy template output and identify high-risk contexts.
- [ ] Add `escapeLegacyHtml()` and `legacyJsonAttribute()` using fork-native naming.
- [ ] Replace high-risk raw text and inline handler interpolation.
- [ ] Add provider-free legacy output safety tests.
- [ ] Add browser smoke coverage for adversarial display values when available.
- [ ] Audit provider factory and common Chat Completions call boundaries.
- [ ] Add empty-response classification and bounded retry.
- [ ] Preserve existing refusal, quota, auth, timeout, and fallback handling.
- [ ] Add provider-free empty-response and request-shape tests.
- [ ] Inspect upstream #240 against fork behavior; port only if duplicated.
- [ ] Run focused Python, JavaScript, provider, narrator, combat, ASCII, and diff checks.
- [ ] Update the closing upstream review ledger with final outcomes.

## Future OpenSpec Outline: `v2-client-foundation-independent-seed`

This is a later change, not part of the current pivot.

### Proposal scope

Vendor the upstream `web/frontend` React/Vite snapshot once as a fork-owned starting point
for `/client`, then adapt it to the fork-native tabletop event contract. No future upstream
sync is implied.

### Design boundaries

- `/` remains the facilitator host.
- `/client` is a player-facing thin client.
- Python remains authoritative.
- Contract, snapshot hydration, reconnect, request IDs, revisions, active-PC state, and
  capability boundaries are defined before broad UI migration.
- Facilitator, toolkit, debug, party-management, and shutdown controls stay out of the
  player bundle.
- LAN operation comes first; internet exposure requires a separate security design.
- Upstream #401 CSS URL behavior is re-evaluated against the vendored code.

### Initial tasks

- [ ] Record the upstream snapshot commit and preserve attribution.
- [ ] Freeze fork-native client/server event contracts.
- [ ] Vendor only the minimum React shell.
- [ ] Serve `/client` without changing `/`.
- [ ] Add typed event, hydration, reconnect, and stale-response tests.
- [ ] Prove one facilitator host with multiple browser clients.

## Execution Sequence

### Gate 0: Plan approval

- Review this plan.
- Confirm no additional upstream lane is required.
- Confirm the final sweep remains limited to #399, #161/#162, and the #240 inspection.

### Gate 1: Governance change

- Create and implement `fork-independence-pivot`.
- Review ADR wording and active documentation.
- Run `openspec validate --specs` and stale-reference checks.
- Do not archive the old upstream plan until the final sweep is complete.

### Gate 2: Legacy UI safety

- Implement the manual #399 behavior port.
- Run source-contract and browser safety tests.
- Confirm no visual or routing regression in the legacy facilitator interface.

### Gate 3: Provider recovery

- Implement bounded empty-response handling.
- Run provider-free request-shape, retry, GPT-5.6, narrator, and combat tests.
- Confirm no empty response is persisted as successful output.

### Gate 4: Finalize independence

- Record #240 result.
- Add the closing ledger to the archived upstream plan.
- Archive both OpenSpec changes after verification.
- Push only to `origin` when explicitly authorized.

## Verification Matrix

### Documentation and policy

- `openspec validate --specs`
- `python3 scripts/check_ascii_compliance.py --summary-only`
- `git diff --check`
- Search active docs for stale `merge-safe`, `merge safe`, and routine upstream-sync claims.
- Confirm ADR-0031, ADR-0002, ADR-0003, and ADR-0030 metadata agree.

### Legacy UI

- `.venv/bin/python -m py_compile` for any modified Python tests/helpers.
- Provider-free source-contract test for the template helpers and call sites.
- Targeted Playwright smoke for quoted, angle-bracketed, ampersand, and event-handler-like
  names when browser tooling is available.
- Existing character-sheet, portrait, party-strip, and web-output contract tests.

### Provider recovery

- `.venv/bin/python` provider-free empty-response retry suite.
- Existing GPT-5.6 Chat Completions contract suite.
- Existing OpenRouter request-shape suite.
- Existing retry-loop and narrator/combat validation suites.
- No live provider call is required for acceptance; any live smoke is bounded and optional.

### Repository safety

- Confirm no `config.py`, API key, provider response, or runtime state is staged.
- Confirm no module artifacts or saved-game files changed.
- Confirm `upstream` push URL remains disabled and no upstream push command is introduced.
- Inspect `git status`, `git diff`, and staged file names before any commit.

## Rollback And Recovery

- Governance changes are documentation-only and can be reverted without data migration.
- The UI safety port and provider retry port MUST remain independently revertible.
- If the UI safety port causes a rendering regression, revert the affected call-site group,
  retain the helper tests, and narrow the next patch.
- If empty-response retry changes provider timing or request shape, disable/remove the
  helper and restore the prior call boundary; do not alter model configuration as a workaround.
- If any test reveals a mechanical, publication, or state-authority regression, stop the
  sweep and leave the remaining upstream work unported.
- Do not use destructive reset, clean, or checkout commands to recover the worktree.

## Expected End State

After this plan is complete:

- ADR-0031 is the canonical fork-governance decision.
- ADR-0002 and ADR-0030 are historical superseded decisions.
- ADR-0003 describes internal extension discipline without upstream obligations.
- Active repository guidance no longer promises merge-safe upstream parity.
- `plans/upstream-merge-0826.md` is archived with a final review record.
- Only the approved #399 and #161/#162 behavior ports, plus any confirmed #240 fix, are
  implemented from the final sweep.
- Upstream remains a read-only historical remote with no routine fetch cadence.
- The fork's own tests, security stack, state authority, and publication contracts remain
  the source of truth.
- The future React client is a one-time fork-owned vendor effort, not a downstream merge lane.
