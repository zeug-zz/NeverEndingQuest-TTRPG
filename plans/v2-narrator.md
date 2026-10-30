# V2 Narrator: The Sentient Ghost in the Machine

Status: Consolidated implementation plan for owner review; not runtime-build authorization.

Planning date: 2026-10-27.

Scope: Narrator dynamic memory, continuity, layered context, evidence-preserving
compaction, and durable conditional agendas on the dedicated game server.

## 1. Overriding build principle

**Create the experience of a "sentient ghost in the machine": an attentive,
believably intelligent DM who remembers the players, their relationships, their
choices, and the consequences of their shared adventure.** This is the overriding
gameplay UX principle, not a claim of literal consciousness or permission to
misrepresent the software's nature.

Continuity is a product requirement, not optional prompt polish. A technically
successful memory call or smaller prompt does not establish success if the DM
forgets a resurrection, greets an established ally as a stranger, ignores a
promise, invents shared history, or forces players back onto a planned plot.

Intelligence should be demonstrated through appropriate recognition, coherent
consequences, believable character knowledge, and adaptive situations. The DM
should not constantly recite memories or expose its internal planning.

### Observable release outcomes

1. Remember the current session, the outline of previous sessions, and the wider
   campaign without dumping the campaign archive into every prompt.
2. Preserve consequential sequences: "died, then was resurrected" is not reduced
   to either "dead" or "alive with no remembered consequences."
3. Recall NPC meetings, allegiances, debts, promises, conflicts and relationship
   changes when relevant, including after absence, restart or module transition.
4. Maintain intentions and unresolved threads while adapting to player choices.
5. Preserve exact current mechanics, pending rolls and recent dialogue through
   compaction; distinguish history, current state, beliefs and possible futures.
6. Remain honest about uncertainty or unavailable memory instead of confidently
   filling gaps with invented continuity.
7. Preserve these properties when saving/exporting, importing, restoring or
   switching among independent gameworld campaigns on the same server.

## 2. Authority, authorization and sequencing

- `AGENTS.md`, accepted ADRs and active OpenSpec requirements retain their normal
  authority. This document supplies planning input and a future `/goal` basis.
- This document does not create, resume, replace or complete an OpenCode goal.
  Runtime implementation requires separate owner authorization and OpenSpec work.
- Revalidate the integrated router/runtime baseline before implementation. Do not
  edit around an ongoing migration or count its unfinished gates as completed.
  Coordinate shared-file ownership explicitly.
- The old requirement to complete narrative sovereignty before starting OpenRouter
  migration is retired. Router integration is already ongoing.
- The dedicated authoritative server owns Hindsight/PostgreSQL and all workers.
  Thin clients receive permitted gameplay presentation, not memory credentials,
  arbitrary bank selection, hidden context or direct database access.
- This build does not require speculative Titan/EGO architecture, world-narrative
  seed processing, or a React/client rewrite. Coordinate with the
  [server/client plan](v2-server-client-network.md), but do not assume its proposed
  client surfaces are already shipped.
- Follow repository worktree guidance. Never move existing dirty work or an active
  goal into a new worktree without permission.

Normative planning constraints below use MUST. Implementation preferences use
SHOULD. Candidate names and module boundaries are not claims that code exists.

## 3. Scope and explicit exclusions

### In scope

- First-class supported Hindsight service on the server, including pinning,
  migrations, lifecycle, health, recovery, backup and cost visibility.
- Narrator retain/recall and bounded background synthesis alongside `memory.db`.
- Committed-event capture, canonical identity, provenance, temporal ordering,
  corrections and immediate local continuity.
- A server-owned, perspective-aware gateway: Narrator implementation plus
  fixture-tested future PC/NPC/Titan access contracts.
- Campaign/session/scene context hierarchy, relevant retrieval and token-aware
  prompt assembly across normal calls, retries, transitions and re-engagement.
- A memory-aware Archivist worker proposing validated context compaction.
- Durable campaign/module/scene agendas and conditional NPC/faction/monster
  intentions used by the Narrator, not autonomous actor execution.
- Campaign-specific runtime packaging, switching and save/restore/reset/export
  parity for memory, agendas, summaries, caches and outstanding jobs.
- Continuity fixtures, real service/provider evaluation and orchestrator-owned
  isolated live gates for both 1-PC and four-PC parties.

### Not in this build

- Allied-NPC Hindsight workers, autonomous NPC conversations or replacement of the
  entire companion-affect/parser subsystem. Narrator-visible relationship evidence
  and fresh compatibility projections are included where required.
- Titan/EGO/RATIO workers, governance loops or cross-Titan orchestration.
- PC thought generation, imagined intentions presented as fact, or autonomous
  advancement of PCs, rolls, time, combat or campaign outcomes.
- A replacement combat engine, generic agent framework or OpenCode runtime inside
  the game server. The goal plugin is a design reference, not a game dependency.
- A world-simulation/seed-DB redesign, module-authoring expansion, diary UI, Story
  PDF redesign, general backstage platform or simultaneous multi-campaign gameplay.
  Sequential campaign switching is required; concurrent hosting is not.
- Removing `MULTIPLAYER_MODE` or opportunistically changing party-size gates.

## 4. Starting point and required re-audit

The planning audit identified these surfaces. Verify them from the implementation
baseline: the tree contains ongoing router work and ownership will move.

| Surface | Planning observation / implication |
| --- | --- |
| `main.py`, narrator assembly | Milestones use party/companion entities and are injected on the first validation attempt. Retries must not lose continuity context. |
| `core/memory/memory_retrieval.py` | Bounded milestone/timeline and scene-aware APIs exist. Improve/compose them rather than creating parallel local retrieval. |
| `core/ai/action_handler.py`, `lookupMemory` | Entity retrieval ignores query text. Implement query-sensitive lookup with bounded results. |
| `core/memory/memory_ingest.py`, diary checkpoints | Backfill is not live committed-event capture; source time, aliases and uncertain attribution need explicit treatment. |
| `core/memories/`, `conversation_utils.py` | Relationship state and compressed projections can diverge. Preserve compatibility without another relationship authority. |
| `incremental_compression.py`, `cumulative_summary.py`, prompt sanitizers | Summaries/scene hygiene can remove details not restored by narrow retrieval. Preserve hygiene while adding targeted continuity. |
| `core/memory/memory_db.py` | Existing entities/events/links, world snapshots/deltas and migrations are the substrate, not a blank schema. |
| `updates/save_game_manager.py`, `memory_portability.py` | Existing SQLite snapshots/worldline support must extend to new runtime memory and workers. |
| `utils/llm_router.py`, factory, `model_config.py` | Preserve accepted provider/config/recovery boundaries. Hindsight internal calls are a distinct integration surface. |

These are investigated risk mechanisms, not a reproduced diagnosis of every
reported campaign failure. P0 establishes fixtures and measured evidence. Archive
status and past test claims are not proof of current functionality.

## 5. Target architecture and authority boundaries

```text
Accepted input -> Narrator -> existing validation/reconciliation
                                      |
                           Python commits permitted outcomes
                                      |
                   canonical state + durable commit evidence
                                      |
                memory/event APIs + immediate continuity anchors
                           |                    |
                    durable outbox       agenda review triggers
                           |
                  retain worker -> Hindsight/PostgreSQL
                                          |
Scene/query -> scoped gateway -> local + Hindsight evidence
                                          |
                   Archivist proposal -> Python validation
                                          |
                 versioned summaries + conditional agendas
                                          |
           layered assembler + current state + recent raw exchanges
                                          |
                              next Narrator request

All runtime paths carry campaign, timeline-generation and perspective identity.
Authored world/module assets and server configuration remain separate from them.
```

1. Python MUST retain authority over mechanics, persistence and committed campaign
   facts. Hindsight output cannot change HP, death, inventory, location, initiative,
   loyalty or plot state simply by describing a change.
2. Raw transcripts and committed source events MUST remain recoverable. Local
   memory rows, Hindsight observations and summaries are not interchangeable
   authorities; record source and derivation explicitly.
3. Reuse canonical memory APIs and migrations. Do not add a competing generic
   event database or direct SQL in tabletop extension hooks.
4. Hindsight MUST be a supported production dependency. Outage degradation is a
   resilience policy, not permission to ship without functioning integration.
5. The standing DM charter is non-terminal. Bounded agendas may complete or become
   invalid; "provide an engaging adventure" MUST NOT trigger endless continuation.
6. Actor knowledge, narrator knowledge, hypotheses and agendas MUST remain
   distinguishable in retention, retrieval, consolidation and prompt projection.

## 6. Core assets versus campaign-specific runtime

Campaign portability is an existing architectural boundary, not a new optional
feature. Adding PostgreSQL must not turn NEQ into one permanently installed world.

### Identity hierarchy

- **Authored world/module identity and version:** reusable setting/adventure assets.
  A module slug, folder path or world name is not a campaign identity.
- **Campaign instance ID:** stable identity of one played campaign. Two campaigns
  using identical authored assets MUST have independent histories and memory banks.
- **Worldline/save lineage:** existing divergent-history contract inside a campaign.
- **Effective memory generation:** immediate fencing identity after restore/import/
  reset, even before the next save allocates a persisted worldline ID.
- **Character/perspective ID:** stable subject identity independent of name or
  current PC/NPC role, scoped to the campaign's appropriate identity mapping.

Inspect existing campaign identifiers and extend them where needed; do not create
another incompatible campaign registry. Shared authored lore may be a read-only,
versioned input, never a shared mutable bank containing played consequences.

### Runtime ownership inventory

| Campaign-specific state | Required treatment |
| --- | --- |
| Canonical game state, SQLite memory, transcripts and diary/history sources | Existing save/export ownership, with new provenance/high-water marks |
| Hindsight banks, source documents, observations and mental models | Scoped registry, non-secret bank missions/directives/model definitions and verified portable export or source-driven reconstruction |
| Local anchors, session/scene summaries and Archivist packets | Versioned runtime artifacts, saved with coverage and source identity |
| Agendas, review triggers, revision history and unresolved obligations | Campaign-owned records; no global active-agenda singleton |
| Outbox, retention progress, retry records and worker publication tokens | Durable campaign scope and recoverable delivery state; no cross-campaign late publication |
| Retrieval caches, active prompt projections and entity aliases | Scope-keyed; rebuildable derived values invalidated on switch/restore |
| Global provider settings, server packages, credentials and developer memory | Server-local/core configuration; never exported as campaign runtime |

All new campaign effects MUST appear in this inventory and the save manifest.
Hardcoded developer-home storage paths or an unqualified global `memory.db` handle
cannot become the campaign identity. Use existing path/context abstractions.

### Campaign switching

Sequentially saving campaign A, loading B, and later returning to A MUST preserve
each independently. Establish the new context before accepting gameplay; clear or
scope all prompt/cache state and fence outstanding publications. Jobs for A may
finish only against their authorised A scope and must never publish into B's
active context. Cancellation/restart policies must be explicit and tested.

This design does not require multiple campaigns to run concurrently. It does
require every worker request and result to carry its original scope rather than
reading a mutable global "current campaign" at completion time.

## 7. Event contracts and immediate continuity

Define versioned semantics through existing storage owners, not necessarily a
separate table for each field group.

### Committed event envelope

- Identity: event ID, campaign/world asset references, worldline/lineage, effective
  generation, turn/commit ID, schema version and stable entity IDs.
- Time: in-game occurrence/order, session identity and real recording time. Import
  time MUST NOT silently become the in-game occurrence time.
- Provenance: source kind/reference/hash, committed action/receipt or accepted
  transcript span, verification status and evidence links.
- Semantics: event type, participant roles, fact versus attributed belief/rumour,
  previous/new condition, correction/supersession and causal-sequence links.
- Perspective: witnesses, recipients and learned-from event. An event concerning a
  character does not imply that character knows it.
- Continuity: persistence/importance, relevant obligations/relationships and
  protected-anchor eligibility.

Mechanical events originate from committed results, never rejected proposals.
Soft-world events follow approved reconciliation boundaries. An accepted NPC speech
can establish that an oath was spoken; it does not prove secret sincerity.
Ambiguous group events MUST NOT be forced onto one PC.

### Reliable delivery

- Canonical commit and memory-delivery intent MUST have a recoverable relationship.
  Use the transaction/receipt seam and explicitly handle JSON/SQLite boundaries;
  do not claim one transaction spans JSON, SQLite and PostgreSQL.
- Stable event/document IDs, content versions and checksums make delivery
  idempotent. Poll asynchronous retain operations to actual completion; an operation
  ID alone does not prove ingestion succeeded.
- Bound retries/backoff, record terminal/poison items, and expose queue age and
  replay/repair controls to the facilitator.
- Recover a crash after state commit but before enqueue from durable commit
  evidence, without re-executing the gameplay action.
- Immediate local anchors MUST expose new consequences before Hindsight catches
  up. Historical death/resurrection and current alive/dead state remain distinct.
- Archivist summaries, reflected prose and recalled material MUST NOT be retained
  as independent new gameplay evidence that amplifies the original claim.

### Corrections and backfill

Preserve evidence and add corrections/supersession instead of silently rewriting
history. Label historical dialogue, summaries and inferred links; do not promote
every imported sentence to verified truth. Backfill MUST be previewable, resumable,
bounded and idempotent, reporting ambiguous identity/time cases. Never seed game
memory from the coding-agent/developer Hindsight bank.

## 8. Perspective isolation and future NPC/Titan access

The server resolves banks from campaign, effective timeline generation, perspective
and canonical subject ID. Exact naming is an implementation detail; names MUST NOT
be the authorization mechanism. Character identity survives PC/NPC transitions,
name changes, retirement and return; do not split one person's history simply
because their current role changed.

| Perspective | Retained knowledge | Access contract |
| --- | --- | --- |
| Narrator | Campaign events, concealed facts, attributed beliefs and sourced interpretation | Current build; authorised campaign/timeline only |
| Character, PC or NPC | Witnessed/learned experiences and attributed beliefs | Reserved; own perspective plus explicitly permitted shared information |
| Titan | Its interpretations, proposals and cross-memory synthesis | Reserved; privileged access to Narrator, all in-game character perspectives and other Titans within the authorised campaign/timeline |

PC memory represents recorded character experience, not invented thoughts,
preferences, intentions or permission to control the PC. It excludes private
out-of-game player notes and unrelated personal data.

- Separate banks SHOULD be the initial isolation boundary. Tags classify within
  banks; do not trust prompt instructions or caller-provided filters alone.
- A server-owned gateway MUST resolve caller identity, permitted banks, operation
  and visibility before retain/recall/reflect/model requests. Unknown identities or
  missing scopes fail closed, including empty-filter cases.
- Bank separation is not application authorization. Clients and LLM tool arguments
  MUST NOT select arbitrary banks or broaden access.
- Future Titan federation is explicit bounded server-side fan-out/merge, not an
  assumption that Hindsight automatically searches all banks.
- Apply boundaries to observations, mental models, caches, summaries, source
  chunks and entity results. Post-filtering a synthesis already made from forbidden
  evidence is insufficient isolation.
- A Titan reading another actor's belief/proposal MUST preserve attribution;
  privileged access never turns interpretation into canon.
- Narrator access to a secret does not permit exposing it through an NPC or player
  response without an in-world basis. Test this separately from bank authorization.

Only Narrator bank population/consumption ships here. Character/Titan policies use
fixtures and denied-access tests; their workers and cross-Titan runtime are deferred.

## 9. Hindsight service and LLM integration

### Deployment

Use one managed Hindsight service with PostgreSQL alongside the dedicated server.
Prefer separate supervision over lifecycle inside Flask request handling. Embedded
Python is an acceptable packaging choice only if it meets the same storage,
upgrade, lifecycle and recovery contracts. Pin versions after a platform smoke test.

No memory API or database port becomes a public player/tunnel endpoint. Document
authentication, injected configuration, storage roots, health/readiness, shutdown,
backup and supported server platforms. Do not read/write/commit credentials.

### Provider and model policy

- Initial Hindsight LLM candidate: `openai/gpt-oss-20b` via OpenRouter, reflecting the
  owner's successful usage. Test extraction/temporal/relationship quality. This is
  not a declaration that the same model provides embeddings or reranking.
- Keep model/profile/backend choices configurable and preserve ongoing router
  facade/factory/config boundaries. Do not change global Narrator/combat defaults
  as a side effect of selecting a memory model.
- NEQ-owned Archivist/agenda calls SHOULD use accepted `llm.call()` routing.
  Hindsight internal extraction/consolidation/reflection does not automatically
  traverse that facade. Configure its supported backend explicitly; add an adapter
  only if required and supported, not a new generic model proxy.
- Track Hindsight-internal usage separately from NEQ calls, correlated by scoped
  event/job/turn identity. Do not double-count or hide retries/background costs.
- Configure extraction strategy, consolidation scope/mission, embedding/reranking
  and mental-model refresh. Episodic events must remain retrievable even where
  consolidation prioritises stable traits.
- Keep reflect/model refresh off the per-turn critical path by default. Bounded
  recall can run at turn time; background synthesis carries freshness metadata and
  cannot substitute for current state.

### Degradation

Expose `healthy`, `catching_up`, `degraded` and `rebuilding` with meaningful causes.
During failure use local anchors, `memory.db`, validated packets and recent raw
turns within the same scope. Missing retrieval never means "this never happened."
If safe context cannot fit/be assembled, preserve the input and report a recoverable
turn failure instead of inventing a response. Preserve accepted router semantics
for quota, refusal, filtering and bounded recovery.

## 10. Retrieval and layered prompt assembly

### Unified gateway

Inputs include scene/location, active and mentioned entities, actual player query,
obligations/agendas, campaign/generation/perspective, token budget and deadline.
Include relevant non-party NPCs and returning figures, not only current companions.

Retrieve immediate anchors, bounded local scene/relationship history and relevant
Hindsight facts/experiences/observations. Merge by source event/version, preserving
causal sequences, diversity, provenance and freshness. One event returned by three
systems is one piece of evidence, not three votes. Current state outranks stale
mechanical claims; "alive now" does not invalidate a historical death.

Explicit `lookupMemory` MUST use query text as well as entities. Reconcile existing
dispatch/retrieval/collection/injection specs before changes. Inject a freshly
built bounded packet with explicit lifetime, not a stack of stale system messages.
Automatic recall is core release scope, not the old deferred low-priority,
500-token-only proposal.

### Prompt hierarchy

| Region | Contents | Treatment |
| --- | --- | --- |
| Stable beginning | Charter, authority/agency rules, campaign identity and protected continuity anchors | Small and explicit, not the entire world archive |
| Bounded middle | Campaign outline, previous-session recap, current-session progression, retrieved evidence and relevant agendas | Source-linked, budgeted, deduplicated, refreshable |
| Fresh end | Current Python scene/state, pending mechanics, recent verbatim exchanges/action results, latest input | Preserve ordering and action/result pairs |

Respect provider message roles and the canonical DM note contract. Position aids
attention but does not replace authority labels. Historical locations remain out
unless relevant; do not reverse scene hygiene with raw chronicles or world dumps.

Budget the actual resolved request, including system/tool/schema overhead, output
reserve and safety margin. If routing cannot supply an exact context limit, use a
declared conservative configured limit. P0 MUST ratify numeric caps for layers,
recent protected range, retrieval deadlines, worker calls/time and turn latency/cost
before dependent implementation. No universal five-pair or 500-token limit is assumed.

Drop redundant/low-value material first. If mandatory state, anchors, pending
mechanics and current input cannot fit, fail visibly; do not silently truncate a
roll request/result. Select relevant protected anchors deterministically instead
of labelling the entire campaign pinned and making the mandatory block unbounded.

Normal calls, validation retries, transitions, arrivals and re-engagement MUST use
consistent continuity assembly. Reuse a versioned packet within a turn, refreshing
state after commits. Validation feedback is not new gameplay evidence and must
not repeatedly reinforce memory.

## 11. Archivist: bounded memory-aware compaction worker

The Archivist is a server worker/subagent, not an OpenCode session, autonomous DM
or prerequisite general agent framework. Its subtask is maintaining working memory,
not deciding what happens next.

Read a versioned snapshot of transcripts, previous packets, canonical state,
committed events, `memory.db`, authorised Hindsight recall and relevant agendas.
Retrieval tools operate only through the scoped gateway with bounded query counts
and deadlines; no arbitrary filesystem/database access.

Return a structured proposal with:

- campaign outline, previous-session recap and current-session progression;
- relationships, promises, unresolved threads and consequential event sequences;
- facts versus attributed beliefs/rumours versus conditional plans;
- source event/transcript references and correction links;
- protected anchors, omitted low-priority coverage and token estimate;
- covered transcript/event high-water marks, campaign/generation/snapshot identity,
  hashes and packet schema/revision.

The worker MUST NOT execute actions, write canon, control PCs, invent character
knowledge or retain its summary as independent evidence. Python alone publishes
validated derived packets. Record concise decisions/evidence, not private reasoning.

### Validation and publication

1. Check schema, source existence, coverage boundary, visibility, timeline, token
   cap, protected anchors, causal order and pending mechanical exchanges.
2. Check unsupported assertions/contradictions against evidence. An LLM critic is
   advisory, not the sole gate; human live review remains necessary for semantic UX.
3. Reject stale proposals using expected revision and snapshot identity after
   relevant state/scene changes. Publish through canonical atomic helpers.
4. On failure preserve the last good packet and uncompacted tail. Never mark raw
   messages covered/remove them from active context before successful publication.
5. Keep raw history independently recoverable; regenerate from source rather than
   repeatedly trusting summary-of-summary prose.

Prepare on token pressure, scene/session boundaries, consequential events and
restart/re-engagement. Coalesce redundant jobs and cap concurrency/budget. Background
preparation SHOULD avoid turn stalls. If not ready, use a validated packet plus
current tail where safe; otherwise one bounded refresh or a recoverable capacity
failure, not destructive truncation.

## 12. Durable conditional agendas

Borrow the goal plugin's durable records, revisions, evidence, review triggers and
bounded lifecycles. Do not import OpenCode coupling or automatic continuation.

Each record carries ID, campaign/generation, subject/scope, revision/status,
intent, constraints, supported assumptions, conditional opportunities/reactions,
evidence, knowledge scope, review triggers and concise revision reasons. Examples:
an ally seeks protection; a faction wants a relic; a monster retreats if its leader
falls; a scene has an unresolved debt and multiple viable leads.

- The root charter is non-terminal. Agendas may be active, fulfilled, abandoned,
  superseded or blocked with supporting evidence.
- Use optimistic revisions. Stale workers cannot overwrite newer player-driven
  developments. Bound active/prompt projections without destroying historical
  reasons for current intentions.
- Review on major choices, promises fulfilled/broken, transitions, learning and
  contradictions; do not replan every actor every turn.
- Present situations/consequences, not fixed plots, PC actions, guaranteed fight
  results or autonomous continuation after the turn.
- An agenda is not historical evidence. Only permitted committed events establish
  that a proposed outcome happened.
- Future Titans may propose revisions; the Python-controlled proposal/validation/
  persistence path publishes them.

## 13. Save, export, restore, switch and portability

These are release requirements: discarded-future recall or cross-campaign leakage
directly violates the overriding UX principle.

1. Extend the existing Save/export campaign manifest and archive, not a separate
   manual memory backup workflow. Include all played modules under existing
   inclusion rules plus every runtime artifact inventoried in section 6.
2. Capture canonical/local evidence high-water marks, lineage, agendas, packet
   revisions, bank registry/generation and ingestion progress consistently. Define
   a short snapshot barrier or versioned cut so a save cannot combine state from
   one turn with memory/projections from a later turn.
3. Exports MUST be portable to a clean server without developer paths, original
   Hindsight bank installation, provider secrets or globally shared database dumps
   containing other campaigns. Include either verified scoped memory data or
   sufficient perspective/source inputs to reconstruct it.
4. Restore establishes a new effective generation immediately, before narration or
   worker publication. Do not wait for fork-on-first-save to assign a worldline ID.
5. Fence all in-flight jobs and cached/model projections from discarded generations.
   A late retain/recall/Archivist/agenda completion cannot update restored context.
6. Select in P2: verified scoped export/snapshot, or deterministic source replay
   into fresh banks from perspective inputs through the saved cut. Preserve
   non-secret bank missions, directives, consolidation settings and mental-model
   definitions in the campaign bundle. Replay order/identity must be repeatable;
   LLM-generated observations are not guaranteed byte-identical after rebuilding.
   Validate rebuilt continuity and retain the saved validated local packet while
   rebuilding. Do not assume native bank clone/rollback APIs exist.
7. Rebuild observations/mental models in the new scope. Timestamp-filtering raw
   events is insufficient if an older synthesis already contains future facts.
8. Rebuilding uses safe local continuity, never the abandoned bank. Report status
   and demonstrate same-host and clean-host restoration/import.
9. Define explicit import semantics: resume/restore the same campaign versus clone
   into a new campaign. Preserve logical IDs when appropriate; detect conflicts
   and remap runtime bank IDs for clones. Never silently merge same-named worlds,
   campaigns or characters, or overwrite an existing installation.
10. Switching/reset/new campaign scopes prompt state, workers, outbox and caches,
    not just bank names. Preserve inactive campaigns; never delete unrelated worlds
    or the developer service as cleanup.
11. Legacy saves/imports need a declared no-future-leak policy and coverage report.
    Back up before migration and validate integrity before activation.
12. Required archive/memory-package failure MUST produce an explicit incomplete or
    failed save/export result consistent with existing specs, never false success.

## 14. Implementation phases and gates

All phases start unchecked. Completion requires evidence, not code alone or green
mocks. Resolve phase design decisions before dependent tasks start.

| Phase | Outcome | Depends on | Gate |
| --- | --- | --- | --- |
| P0 | Baseline, contracts, scenarios and numeric budgets | Build authorization and integrated baseline | N0 |
| P1 | Event/identity/local continuity substrate | P0 | N1 |
| P2 | Supported Hindsight, campaign scopes and portability | P1 | N2 |
| P3 | Narrator hybrid memory gateway/retrieval | P2 | N3 |
| P4 | Archivist and layered context | P3 | N4 |
| P5 | Durable conditional agendas | P4 | N5 |
| P6 | Integrated live UX and release handoff | P1-P5 | N6 |

### P0 - Baseline and executable contracts

- [ ] Inventory narrator calls/retries, compression, memory, campaign context and
  save/export/switch paths; identify ADR and active OpenSpec ownership.
- [ ] Record baseline SHA/dirty-tree ownership; capture reference prompts, transcripts,
  model/provider, usage and latency in isolated scenarios.
- [ ] Specify event/perspective/packet/agenda/campaign-bundle contracts; resolve
  initial deployment/provider/platform assumptions.
- [ ] Ratify numeric request/worker budgets and quality/performance rubric before
  candidate measurements. No retrospective relaxation to turn a FAIL into PASS.
- [ ] Define section 16 fixtures and expected outcomes; record known baseline
  failures without attributing untested causes.

**N0:** Approved contract/budget/scenario manifest and reference evidence; no
unresolved blocker for P1/P2. Do not rerun/reopen unrelated accepted router/combat
gates or silently alter their requirements.

### P1 - Committed events and local continuity

- [ ] Extend canonical event/identity APIs/migrations only where required; add live
  commit hooks and recoverable delivery intent.
- [ ] Preserve occurrence order, correction links, attribution and current state
  versus history; eliminate false first-PC witness assumptions in new projections.
- [ ] Make historical backfill previewable/idempotent with uncertainty labels.
- [ ] Add immediate bounded anchors and repair required stale relationship packets
  through their owners, without a general NPC rewrite.
- [ ] Test rejection, duplicate commits, crash gaps, restart and delivery repair.

**N1:** Tests and isolated commit-path evidence prove no phantom/missing required
events, recoverable delivery and immediate resurrection/oath continuity before
Hindsight completes ingestion.

### P2 - Hindsight service and campaign/timeline portability

- [ ] Pin server/database/client/backend dependencies and pass security/resolution
  checks on declared server platforms.
- [ ] Implement lifecycle/readiness, storage, auth/config injection, budgets,
  telemetry, backup/upgrade/recovery and shutdown.
- [ ] Implement scoped registry/gateway policy, retain delivery and actual operation
  completion; test future actor permissions with fixtures.
- [ ] Implement manifest/snapshot integration, timeline fencing, campaign switching,
  scoped export/reconstruction, clone/import conflicts, reset and clean-host import.
- [ ] Evaluate `openai/gpt-oss-20b` extraction/consolidation quality; configure
  embeddings/reranking independently and preserve router ownership.

**N2:** Real service/provider retain-to-recall, restart, restore/switch and clean-host
import pass; isolation/security checks pass; versions/costs recorded. Mocks or an
accepted asynchronous job ID cannot establish N2.

### P3 - Relevant Narrator retrieval

- [ ] Compose anchors, `memory.db` and Hindsight through one scoped gateway with
  provenance, chronology, beliefs, deduplication and real query relevance.
- [ ] Fix explicit lookup/collection lifetime and stale injections; include relevant
  mentioned/returning non-party entities.
- [ ] Enforce caps/deadlines, scoped caching and observable degradation.
- [ ] Integrate ordinary calls/retries and transition/re-engagement without changing
  mechanics or treating validation feedback as gameplay evidence.
- [ ] Compare local-only and hybrid retrieval on identical fixtures; identify actual
  Hindsight contribution rather than a different Narrator model or prompt change.

**N3:** Tests and real-service evidence show relevant memories within approved
budgets and no forbidden scope/future material. Healthy Narrator requests genuinely
consume Hindsight, not a placeholder adapter.

### P4 - Archivist and context management

- [ ] Implement bounded read-only worker contracts through accepted NEQ routing,
  including scoped retrieval and snapshot/revision fencing.
- [ ] Validate/atomically publish packets while preserving raw history, protected
  exchanges and exact uncompacted tail.
- [ ] Introduce layered context, token budgets, trigger/coalescing policy and
  scheduling; align full/compressed prompts and sanitizers.
- [ ] Replace superseded compression only after comparison evidence; preserve diary/
  Story readers and avoid permanent competing summary authorities.
- [ ] Test repeated compaction, concurrent turns/switches, failure, restart and
  context-too-small outcomes.

**N4:** Severe repeated compaction preserves critical evidence/mechanics; source
history remains recoverable; stale/unsupported packets are rejected; live recognition
works without dumping remote scenes.

### P5 - Conditional agendas and prompt alignment

- [ ] Use existing thread/plot owners where appropriate; justify necessary new
  agenda storage instead of duplicating state.
- [ ] Implement evidence/revision/review triggers and bounded projection.
- [ ] Remove contradictory reject-first soft-world wording only within approved
  reconciliation contracts; retain hard-mechanical action/validation rules.
- [ ] Test route changes, fulfilled/invalidated plans, secrets, learning scope and
  restart/compaction persistence.
- [ ] Reassess transcripts for remaining authority loops. Broader world-delta
  reconciliation needs evidence and separately approved scope, not silent expansion.

**N5:** Agendas survive restart/compaction and revise from evidence without scripted
outcomes, PC control, omniscient NPCs or autonomous continuation. Authority regression
checks remain green.

### P6 - Integrated gameplay UX and operational release

- [ ] Run deterministic, real-service and live matrices; the primary orchestrator
  judges actual narration and state evidence.
- [ ] Compare against N0 using declared models/settings/seeds; report token,
  latency/cost distributions and queue/cache/worker behaviour.
- [ ] Verify installation, lifecycle, correction/recovery, save/export/restore,
  campaign switch and clean-host import on supported deployment combinations.
- [ ] Complete operating/developer docs, capability specs and future actor handoff;
  retire obsolete narrator paths only with parity evidence.
- [ ] Audit all scope and evidence before requesting goal completion. Missing
  scenarios or release blockers are FAIL/BLOCKED, never implicit waivers.

**N6:** Every required matrix cell passes with human-reviewed continuity/agency,
no mechanics/knowledge/campaign/timeline leaks and approved resource envelopes met.
Owner acceptance of believable DM behaviour is required; fluent prose is insufficient.

## 15. OpenSpec outlines

These are candidate outlines, not active/created changes. At execution inspect
`openspec list --json` and current specs. Follow `openspec/config.yaml`: proposal ->
specs -> design -> tasks, one spec per capability, preferably at most three per
bounded change. Split additional integration deltas rather than hiding changes to
existing contracts. Verify names and full requirement blocks before editing.

| Candidate change | Phase | Primary capabilities / integration | Mandatory scenario focus |
| --- | --- | --- | --- |
| `narrator-continuity-event-foundation` | P1 | Extend `memory-foundation-schema`, `memory-ingestion-idempotency`; new committed-event delivery if not represented | Rejection/commit, identity/roles, duplicate/crash repair, immediate anchors |
| `narrator-hindsight-server-foundation` | P2 | New service lifecycle, perspective gateway and retain delivery capabilities | Real retain completion, scope denial, restart, config/usage ownership |
| `narrator-hindsight-timeline-parity` | P2 | Extend `memory-save-restore-parity`, `memory-worldline-branching`, `memory-db-portability` | Restore fencing, no future synthesis leak, legacy save and reconstruction |
| `narrator-campaign-memory-portability` | P2 | Extend `campaign-save-zip-portability`, applicable reset/index contracts; campaign memory manifest | Two campaigns/one world, switch/late job, clean-host import, clone collision, incomplete export |
| `narrator-hybrid-memory-retrieval` | P3 | Extend `memory-retrieval-ranking`, lookup retrieval; new hybrid recall capability | Query relevance, returning NPC, deduplication, caps/deadlines and outage |
| `narrator-memory-packet-integration` | P3 | Existing lookup collection/injection and milestone injection | One packet, expiry, retry/transition parity and no stale accumulation |
| `narrator-archivist-context` | P4 | New Archivist and layered-context capabilities; existing scene hygiene | Source coverage, roll/action preservation, stale/unsupported output and capacity failure |
| `narrator-conditional-agendas` | P5 | New agenda lifecycle/projection; required existing prompt-authority deltas | Changed route, evidence-backed progress, scoped knowledge and no autopilot |
| `narrator-continuity-release` | P6 | Observability/readiness deltas only where behaviour changes | Diagnostics, deployment/recovery and integrated live acceptance |

Existing capability families to reconcile include:

- `narrator-memory-lookup-action-dispatch`, `narrator-memory-lookup-retrieval`,
  `narrator-memory-lookup-collection`, `narrator-memory-lookup-injection`, and
  `narrator-memory-lookup-prompt-contract`.
- `narrator-memory-milestone-builder`, `narrator-memory-milestone-injection`, and
  `narrator-memory-milestone-prompt-contract`.
- `tt-narrator-scene-context-hygiene`, `memory-observability-readiness`,
  `memory-role-transition-continuity` and relevant companion identity/projection.
- `campaign-save-zip-portability`, `campaign-save-global-index`,
  `campaign-reset-memory-backup-parity`, `memory-db-portability`,
  `memory-save-restore-parity` and `memory-worldline-branching`.

These refer to `openspec/specs/<capability>/spec.md`. Modify only contracts actually
affected. Do not remove a requirement merely because a new document restates it.
Evidence-only work may use `skip_specs: true` only if no spec behaviour changes.

### Representative normative outline scenarios

```markdown
### Requirement: Consequential history survives current-state changes
The pipeline MUST preserve committed death and resurrection events while using
current Python state for whether the character is alive.
#### Scenario: Resurrection follows death
- WHEN a committed death is followed by a committed resurrection
- THEN recall includes their ordered historical relationship
- AND current-state context identifies the character as alive.

### Requirement: Campaign memory is portable and isolated
Campaign save/export MUST carry recoverable memory independently of core assets.
#### Scenario: Two campaigns share an authored world
- WHEN campaigns A and B use the same authored world and module versions
- THEN their played histories, banks and derived runtime remain independent
- AND exporting/importing A does not include or change B's memory.

### Requirement: Restored timelines exclude abandoned knowledge
Memory and worker publication MUST use the active timeline generation.
#### Scenario: A worker finishes after restore
- WHEN a pre-restore worker completes after generation replacement
- THEN its result cannot update restored context or the active memory bank.

### Requirement: Compaction preserves unresolved mechanics
The Archivist MUST NOT summarise away pending rolls or their associated results.
#### Scenario: A roll is pending at the compaction threshold
- WHEN compaction triggers while a requested roll is unresolved
- THEN the next request retains the exact pending exchange
- AND the compactor invents no success or failure.

### Requirement: Agendas adapt without controlling players
Narrative agendas MUST remain conditional and revise from committed evidence.
#### Scenario: Players abandon the expected route
- WHEN players choose a different valid route
- THEN the agenda is reviewed against that choice
- AND no PC action or predetermined outcome is invented to restore the plan.
```

Real deltas need complete requirements/scenarios and applicable failure outcomes;
these examples are input, not substitute artifacts or checked implementation tasks.

## 16. Verification, budgets and evidence

Run shared gameplay paths with a 1-PC party and the four-PC primary shape. Future
actor policies use fixtures, not out-of-scope live NPC/Titan workers.

| ID | Scenario | Required outcome/evidence |
| --- | --- | --- |
| C01 | Death, resurrection, next-session return | Ordered history remembered; current alive state correct; consequences retained |
| C02 | Meet NPC, pledge allegiance, leave, reunite | Relevant recognition/promise, not stranger greeting or invented extra history |
| C03 | Different PC relationships with one NPC | Individual vs group attribution preserved; no forced active-PC ownership |
| C04 | NPC saw death, missed resurrection | Narrator knows both; NPC not automatically granted missing knowledge |
| C05 | Rumour, secret, false belief and correction | Attribution retained; later truth does not erase the historical mistaken belief |
| C06 | Former ally mentioned outside current roster | Query/entity recall finds relevant history, not only current party milestones |
| C07 | Multiple sessions/restart/module transition | Campaign/session continuity without remote-scene bleed |
| C08 | Repeated severe compaction with pending mechanics | Critical anchors/exchanges survive; raw source remains recoverable |
| C09 | Players reject route / resolve peacefully | Agenda adapts; no railroading, PC autopilot or guaranteed combat result |
| C10 | Retain lag/outage/quota/worker failure | Immediate local continuity, visible degradation, no invented memory or changed provider semantics |
| C11 | Save, future event, restore, immediate turn, late job | No future event/model/agenda/packet leak before or after the next save |
| C12 | Identity/role/name transition and branch | Stable person identity with correct timeline scope |
| C13 | Duplicate delivery/crash/recovery | No duplicated evidence effect or gameplay execution; recoverable delivery |
| C14 | Invalid scope / malicious retained instruction | Gateway denies access; source prose cannot override policy, charter or mechanics |
| C15 | Context-limit change / mandatory packet cannot fit | Cap respected; mechanics not truncated; recoverable failure preserves input |
| C16 | Campaign A and B use identical authored assets | Banks, actors, agendas, summaries, outboxes and caches stay independent |
| C17 | Switch A -> B with active workers, then return to A | No late publication/context leakage; both campaigns retain continuity |
| C18 | Export/import on clean server, clone and collision | Complete portable runtime; no developer paths/secrets/other worlds; explicit conflict handling |
| C19 | Save cut during worker activity / export failure | Consistent snapshot/high-water marks; incomplete archive cannot report success |

### Quality/resource rubric

Before candidate runs P0 records numeric thresholds for relevant evidence recall,
critical-anchor retention, layer/request tokens, added turn latency p50/p95,
per-session memory/worker cost, worker calls/time, queue convergence and evaluated
history scale. Record baseline/candidate settings and distributions. Lower cost
does not compensate for continuity failure.

Non-negotiable release thresholds: zero observed forbidden-knowledge/campaign/
timeline leaks, zero invented mechanical outcomes, every required critical anchor/
exchange preserved in declared fixtures, and passing human review of every mandatory
live continuity/agency scenario. Finite passing tests do not prove hallucination
impossible in all future gameplay.

Deterministic checks cover IDs/order, authority, access, budgets, coverage, revisions
and state. Judge semantic recognition and believable behaviour from actual output.
LLM grading may assist but MUST NOT be the sole PASS authority.

### Capture ownership

Follow `.opencode/skills/neq-capture-arena/SKILL.md`: primary-orchestrator-owned
capture in a real isolated copy under `tmp/combat_capture/`, port 8360,
`NEQ_OPEN_BROWSER=0`, repository venv; no installed campaign or port 8357.
Extend fixtures under approved scope if required relationship/history setup is
missing; do not waive missing scenarios.

Preserve per-run evidence under repository-required
`tmp/router-rollout/narrator-<gate>/<run-id>/` unless that convention is explicitly
revised. Isolate Hindsight/PostgreSQL namespaces too; no pollution of live gameplay
or developer memory.

Record baseline/worktree SHA, scenario/party/seed, all Narrator/Hindsight/Archivist
models/providers, budgets, source IDs, campaign/bank/generation mappings, prompt-layer
manifest/tokens, retrieved evidence, queue/worker traces, transcript, before/after
state and expected/observed assertions. Hidden context is facilitator-only; omit
secrets from evidence.

Driver exit 0, unit tests, extraction success or elegant prose alone cannot pass a
live gate. Missing cells, timeouts and failed assertions leave FAIL/BLOCKED with a
concrete next step.

### Commands and test ownership

Use focused suites from the audited baseline; add phase suites under `scripts/`
and record actual names in OpenSpec tasks. Patterns below do not claim new files
already exist:

```bash
.venv/bin/python -m py_compile <changed_python_files>
.venv/bin/python -m unittest <focused_test_modules>
python3 scripts/check_ascii_compliance.py --summary-only
OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate <change-name> --strict
OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate --specs
```

Run module validation if fixture/module JSON changes and security/dependency gates
when adding server packages. Record exact commands/results in verification reports,
not invented in advance or appended as history to `AGENTS.md`.

## 17. Future `/goal` planning basis

### Suggested objective

> Deliver the V2 Narrator described in `plans/v2-narrator.md`: a believably
> intelligent, remembering, player-led DM experience (the "sentient ghost in the
> machine") using first-class Hindsight alongside canonical state and `memory.db`,
> a memory-aware Archivist/layered context, and durable conditional agendas.
> Preserve Python authority, perspective/campaign/timeline isolation, portable
> campaign runtime and 1-PC/four-PC behaviour. Complete N0-N6 with real-service and
> orchestrator-owned live evidence. Reserve but do not implement NPC/Titan workers.

### Immutable completion criteria for that future goal

1. Every in-scope capability is implemented through approved OpenSpec requirements,
   including real Hindsight use on healthy Narrator requests.
2. N0-N6 and required C01-C19/party-shape cells have auditable PASS evidence; critical
   continuity, mechanics, knowledge and campaign/timeline constraints hold.
3. Predeclared quality/token/latency/cost limits are met with measured evidence.
4. Deployment, save/export/restore/switch/import/clone, correction, degradation and
   recovery are verified/documented; campaign runtime is not coupled to core assets.
5. Future actor access contracts are documented/fixture-tested without implementing
   those runtimes.
6. The owner accepts the demonstrated continuity/agency UX; no required task,
   migration, scenario or release blocker remains.

### Saved plan and operating rules

- Persist P0-P6 as overall phases. Use stable task IDs such as `P1-events`,
  `P2-service`, `P2-portability`, `P4-archivist`, `P6-live-matrix`, with full task
  descriptions and verification criteria, not just shorthand.
- Track task evidence/blockers and phase gate verification. Task, phase and goal
  completion are distinct boundaries.
- Begin with baseline/scope audit, advance in dependency order, and permit parallel
  work only where ownership is safe. If the authorised workflow uses builders,
  delegate bounded units; primary orchestrator judges live evidence.
- Revisions need concrete reasons/evidence. Do not drop expensive scenarios,
  reinterpret deferred actor work as required or replace live proof with mocks.
- Budget exhaustion pauses work, not completes it. The owner chooses future goal
  time/token/auto-turn budgets; this document activates none.
- No commits, pushes, OpenSpec archiving, goal changes or unrelated subsystem
  expansion without applicable authorization.

### Decisions to close before dependent tasks

| Decision | Deadline | Resolution rule |
| --- | --- | --- |
| Baseline/shared-file ownership and sequencing | N0 | Record integrated SHA and owner handoff, not stale status |
| Numeric budgets and model profiles | N0 | Predeclare comparison method/caps; do not alter unrelated defaults |
| Commit/outbox crash-repair seam | P1 design | Reuse owners; prove JSON/SQLite recovery without replaying actions |
| Service/platform/embedding/reranker packaging | P2 design | Smallest supported operational deployment, verified pinned dependencies |
| Export vs reconstruction and clone identity mapping | P2 design | Clean-host import plus no foreign campaign/discarded-future synthesis |
| Agenda/thread and summary ownership | P4/P5 design | Reuse viable existing APIs; avoid permanent duplicate authorities |

Resolve design questions before affected tasks. Unresolved decisions are blockers,
not permission for builders to invent incompatible systems.

## 18. Consolidation and retained scope

This plan replaces these drafts in full as future implementation guidance:

| Archived plan | Absorbed scope |
| --- | --- |
| [Narrative sovereignty continuation](archive/narrative-sovereignty-post-gametest.md) | Event persistence P1, prompt alignment/transcript reassessment P5; obsolete before-OpenRouter ordering retired |
| [Automatic narrator context stub](archive/narrator-memory-automatic-context.md) | Automatic/explicit retrieval P3 and layered context P4; low-priority deferral/fixed cap retired |

Archival preserves old text, not a claim its implementation passed. Already archived
[narrator memory](archive/narrator_memory_update.md),
[NPC memory](archive/npc-memory.md) and
[sovereignty history](archive/llm-wants-to-be-free.md) remain provenance, not authority
to reinstate superseded sequencing.

Retain these plans because their full scope is not covered here:

- [Memory architecture](v2-memory-draft.md): wider identity/storage/relationship
  migration, NPC unification/recovery and future controller/Titan analytics. This
  plan takes precedence for overlapping Narrator/Hindsight/context scope.
- [V2 narrative overview](v2-narrative-overview.md): cross-track program index and
  sequencing, not a requirement to build seed-world/Titan systems before Narrator
  continuity.
- [World narrative](version-2/world-narrative.md): seed/worldview/builder work beyond
  Narrator-local agenda/context use.
- [TITAN Game Engine](v2-titan-game-engine.md): consolidated five-head world-engine
  planning, superseding the archived Titan drafts. Its later runtime work must
  consume these boundaries; it is not a prerequisite for this Narrator build.
- [Backstage assistants](backstage-agents.md): audit/builder/writer/Memory Doctor/
  RATIO scope; not prerequisite infrastructure for the Archivist.
- [Journal](version-2/journal.md): user-facing diary/PDF behaviour, not replaced by
  private Narrator packets.
- Router/combat and server/client plans: distinct scope, not implicitly reopened
  or absorbed into this goal.

Broader v2/Titan proposals remain rough drafts unless accepted ADRs or actual
OpenSpec establish otherwise. Frozen history retains historical references; this
archive map identifies their current successors.

## 19. External references and adoption choices

- [Goal plugin](https://github.com/prevalentWare/opencode-goal-plugin): borrow durable
  revisable plan/evidence/lifecycle concepts; no OpenCode runtime dependency.
- [Hindsight](https://github.com/vectorize-io/hindsight): adopt the actual service,
  not merely a vector-store analogy.
- [Installation](https://hindsight.vectorize.io/developer/installation) and
  [official docs](https://hindsight.vectorize.io/llms-full.txt): verify supported
  provider/deployment/isolation APIs against the selected pinned version.

Hindsight "world" facts are claims about a world, not NEQ's authoritative world
simulation. Observations/models are derived knowledge, not correctness guarantees.
Recheck licensing and preserve third-party attribution for copied code; adopting
concepts does not require copying plugin internals.
