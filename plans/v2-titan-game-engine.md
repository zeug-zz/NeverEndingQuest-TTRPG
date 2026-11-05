# V2 TITAN Game Engine - Master Plan

Status: Consolidated planning baseline; runtime implementation not yet authorised.
Date: 2026-10-27
Scope: A unified, campaign-scoped, agentic world engine behind the Narrator.
Delivery: One overarching delivery goal, decomposed into focused OpenSpec changes.

## 1. Purpose and overriding experience

Transform NEQ from a predominantly static module adventure into a dynamic,
incrementally disclosed gameworld: people remember, enemies pursue interests,
events develop beyond the party's view, and consequences cross module boundaries.
The player should experience the "sentient ghost in the machine": a strangely
attentive, intelligent world whose surprises make sense afterwards. This describes
an illusion of intelligence and continuity, not literal sentience.

TITAN is one universal engine with five competing, hydra-like heads. Their
elemental forces are volitional: Good, Evil, Order, Chaos and Balance. They are
not earth/water/fire/air elements, physical gods or a hydra that appears in play.

The engine's central loop is:

```text
Committed events + campaign facts + authorised memories + world-seed fragments
  -> five persistent Titan perspectives and conditional agendas
  -> bounded opportunities and intervention proposals
  -> Python validation, declaration, resolution and atomic publication
  -> effective module/world/actor state
  -> knowledge-appropriate disclosure through the Narrator and characters
  -> committed consequences, memory and independently evaluated alignment progress
```

Titans seek supremacy. Their competition is intended to balance outcomes for the
PCs and players: sympathetic forces assist each PC while competing forces create
resistance, temptation and surprise. Balance does not mean cancelling victories,
guaranteeing success, equalising every encounter or controlling player decisions.
The engine safeguards fair, coherent play; the heads pursue conflicting interests.

This document is the current TITAN planning owner. It is not a claim that the
described runtime exists, an instruction to start autonomous execution, or a
substitute for accepted ADRs and active OpenSpec acceptance criteria.

## 2. Authority, supersession and independent plans

### 2.1 Retired Titan drafts

These rough drafts are superseded in full and retained only for design history:

| Former path | Archived copy |
| --- | --- |
| `plans/titan-world_narrative.md` | [Original world-narrative discussion](archive/titans/titan-world_narrative.md) |
| `plans/version-2/titan-integration.md` | [Original integration umbrella](archive/titans/titan-integration.md) |
| `plans/version-2/titan-retune-execution-order.md` | [Original retune sequencing](archive/titans/titan-retune-execution-order.md) |

Do not implement their six-agent pantheon, ten-minute random identity rotation,
free-model mandate, EGO/RATIO prerequisite chain, unrestricted JSON mutation or
old retune checklists. Historical links in archived OpenSpec records may retain
the former paths; they are provenance, not current implementation instructions.

### 2.2 Shared planning ownership

- [V2 Narrator](v2-narrator.md) independently owns Narrator continuity, Hindsight,
  context/Archivist, conditional agendas, perspective isolation and campaign
  portability. TITAN consumes these contracts; it does not expand or block that
  build. Reserved Titan permissions are not implemented Titan workers.
- [World seed handover](neq-world-handover.md) describes the seed artifact and
  public schema. Verify its content claims against the actual delivered artifact.
- [World narrative](version-2/world-narrative.md),
  [memory](v2-memory-draft.md),
  [V2 narrative overview](v2-narrative-overview.md), toolkit and mapping drafts
  remain references for independent work. This plan supersedes their Titan-specific
  identity, scheduling, controller, scoring, world-authoring and dependency assumptions.
- [Backstage agents](backstage-agents.md) and EGO/RATIO/CNS proposals are not TITAN
  prerequisites. Their independent uses are not deprecated by this decision.
- Allied NPC agents are a separate future workstream with shared identity,
  knowledge, memory and proposal contracts. TITAN does not implement or own them.
- Accepted ADRs, repository safety rules and active change-specific OpenSpec
  contracts remain authoritative. Conflicts require explicit reconciliation, not
  silent changes to existing runtime behaviour.

### 2.3 Scope exclusions

No general-purpose agent framework, model-weight reinforcement training,
omnipresent continental simulation, allied-NPC controller replacement, physical
Titan appearances, player mind-reading, automatic alignment conversion, module
topology rewrite, new party-size gates or encumbrance implementation is included.
Do not opportunistically remove `MULTIPLAYER_MODE` or alter router rollout scope.

## 3. Baseline audit and seed-content prerequisite

The review found existing bootstrap entrypoints in `core/memory/memory_db.py`:
`bootstrap_memory_db_from_seed()`, `init_memory_db()` and
`run_memory_migrations()`. This does not establish completed runtime retrieval,
world generation or Titan integration.

Historical, pre-delivery observation (2026-10-27), retained as provenance only:

- SHA-256: `0ed5a2a74cafe26cd6bd82beddbdaa0bdb14964102282e326b4567f7b3b85de7`.
- `inspiration_atoms`: 0 rows; `alignment_profiles`: 0 rows;
  `atom_relations`: 0 rows.
- The installed alignment schema includes `ethical_score`, `moral_score`,
  `balance_score`, `classic_label`, `source` and `confidence`.

Reconciled 2026-11-05: the current handover sections 1-10 record the delivered
pilot main-file hash
`6dbefe49f72733d11cc1ae6c15c41f9ce97435235842192effd9295ab56bb66e`.
The disposable SQLite-backup audit independently finds 41,216 atoms, 3,944
alignment profiles, 240 v1-shaped detail envelopes and zero relations. Its
backup hash differs from the source hash; see
`v2-memory-pilot-p0/baseline-audit.md` for the exact identity and limitations.
The earlier empty-seed observation is superseded, not a current blocker.
The delivered alignment schema lacks the historical `source` column. Full
consumer validation, semantic quality and publication clearance remain open;
240 enriched pilot cells do not establish full-corpus enrichment.

P0 must verify the actual export, integrity, foreign keys, schema/version,
representative fragment quality, alignment distributions and supported retrieval.
The reference seed itself may legitimately have no atom-relation rows; absence
must not be papered over by inventing links. Report missing content explicitly.
A labelled curated fixture can support tests, but cannot satisfy the populated
production-seed release gate. Never overwrite a populated campaign DB to install
a new seed; define additive, versioned import/migration semantics first.

## 4. Five heads and their supreme goals

Every head has a persistent identity, non-terminal supreme goal, private durable
planning perspective and bounded conditional agendas. All operate within one
campaign reality, not five separately authored worlds.

| Head | Supreme direction | Typical expressions and tensions |
| --- | --- | --- |
| Bonum | Increase Good through compassion, protection and mutual aid | Mercy, sanctuary, relief, sacrifice, solidarity; can conflict with rigid institutions |
| Malum | Increase Evil through exploitation, cruelty and corruption | Temptation, domination, predation, betrayal; can assist a PC to secure later leverage |
| Ordo | Increase Order through commitments, coordination and durable structures | Oaths, disciplined forces, predictable exchange, institutions; can support justice or tyranny |
| Chao | Increase Chaos through autonomy, disruption and improvisation | Liberation, mischief, rebellion, unstable arrangements; can free victims or destroy useful order |
| Statera | Increase Balance, incorporating Fate and neutral morality | Counterweights, plural viability, detachment, contingency and resistance to overwhelming dominance |

Good/Evil and Order/Chaos are distinct axes. Bonum and Chao may oppose a lawful
tyrant; Malum and Ordo may strengthen an efficient oppressive state. Statera is
not a sixth morality-neutral head and must not simply undo every other success.

### 4.1 PC patronage and leverage

Each PC should have one or two sympathetic heads, based on declared character
values/alignment and evidence-backed affinities, not invented private thoughts.
Record and review patronage explicitly, including neutral PCs and mixed parties;
do not infer equal spotlight from equal token allocation. PCs can reject offers,
act unexpectedly or advance a rival's interests without losing player control.

A Titan first seeks leverage through a sympathetic PC, then an allied NPC through
ordinary influence, then eligible non-allied actors and world opportunities.
This is a preference, not a rule forcing every action through the party. Aiding
a PC's success is instrumental to the head's goal; PC survival, kills or victory
alone are not evidence that its alignment gained power.

Engine safety and spotlight accounting remain independent of Statera. Competitive
assistance should create viable choices and counterplay, not hidden dice fudging,
inevitable rescues, punishment for refusing patronage or monopolised attention.

## 5. World fragments, facts and incremental disclosure

The seed is a corpus of fantasy-world fragments: motifs, scene/relationship
patterns, archetypes, potential people, creatures, locations and conflicts. These
are potential world facts, not pre-existing campaign history. They supply specific
genre flavour rather than generic LLM villainy or arbitrary pseudo-creativity.
Use only approved distributable seed material and preserve licensing/provenance;
do not reproduce identifiable copyrighted passages as generated campaign content.

### 5.1 Four distinct knowledge classes

1. **Seed possibilities:** reusable fragments not yet instantiated in a campaign.
2. **Committed campaign facts:** established actors, places, relationships and events.
3. **Attributed beliefs/reports:** rumours, mistakes, testimony, propaganda and lies.
4. **Conditional intentions:** agendas, hypotheses, forecasts and possible futures.

Retrieve -> interpret in context -> instantiate with campaign identity -> validate
and commit -> disclose appropriately -> record consequences. This produces a
distinct world per campaign, analogous to divergent multiverse worldlines.

Distinguish commitment from player disclosure. An offscreen event can become a
committed fact before the PCs hear of it; a rumour establishes that a report was
made, not that its content is true. Once committed, even an unseen fact cannot be
silently contradicted. Uncommitted character/world possibilities remain flexible.
Preserve source seed IDs, transformations, event IDs and correction links.

### 5.2 Expanding relevance horizon

- Immediate scene: concrete actors, sensory facts, actionable opportunities.
- Module/local region: selected factions, relationships, resource flows and clocks.
- Wider world: sparse outline, unresolved tensions and a few consequential fronts.
- Expand detail when travel, player interest or causal consequences make it useful.

Maintain a shared versioned world outline with multiple competing agendas, not
competing histories. Outlines describe situations and possible trajectories;
they never prescribe PC choices, guaranteed endings or mandatory plot convergence.
Geographic additions must reconcile stable location IDs and mapping contracts;
TITAN does not bypass Python-owned movement/connectivity or tactical legality.

## 6. Memory, tools and durable planning

Reuse the Narrator's scoped gateway, evidence model, durable agenda primitives,
revision checks and bounded context patterns. Do not couple gameplay to OpenCode
sessions or its goal plugin. Record concise plans/reasons/evidence, not private
chain-of-thought.

Each Titan may read authorised campaign/timeline memory from `memory.db`, Narrator,
PC/NPC perspectives and other Titans' Hindsight banks through server-resolved,
bounded fan-out. It never reads coding-agent memory, unrelated campaigns, private
out-of-game player material or arbitrary banks selected through model arguments.
Privileged recall does not turn another actor's belief or proposal into fact.

Retain Titan interactions across the entire intervention surface: people,
weather, module conditions, promises, world developments and observed outcomes.
This supports coherent cross-module world-building constrained by Python physics.

### 6.1 Minimum domain tool surfaces

- Inspect current scene/state, supported rules and scoped committed events.
- Retrieve seed fragments by genre/theme, affinity, entity kind and context.
- Recall authorised memories, actor timelines and cross-module relationships.
- Read alignment snapshots, prior interventions and available resource budgets.
- Create/review/revise conditional agendas with expected revisions and triggers.
- Propose actor activation/dossier enrichment, world/scene deltas, declarations,
  weather forecasts, information delivery and Narrator presentation packets.
- Inspect validation results and realised outcomes; revise or abandon stale plans.

Tools expose domain operations, not arbitrary filesystem writes, direct SQL,
shell execution or unbounded tool loops. Canonical APIs own persistence.

Every request/result carries campaign ID, effective timeline generation, session,
Titan/actor identity, snapshot/revision, event high-water mark and schema version.
Bound retrieval, tool calls, reasoning/output tokens, elapsed time, concurrency
and retries. Long-horizon planning stays off the player-turn critical path.

## 7. Session leadership and opportunity scheduling

### 7.1 Session identity and random leadership

At an explicit gameplay-session start, Python randomly selects one of five heads
as lead and persists the draw and policy version. Start with uniform random
selection; ratify exact session-boundary semantics in P0. Server boot, browser
refresh, reconnect and worker retry do not create a new session or redraw.

Repeated heads are allowed and intentionally create persistent cosmic weather.
Do not silently force a different winner after a streak. Test mode provides a
reproducible random seed; production draws are recorded and hidden from players.
Save/restore preserves session identity/draw according to explicit lineage rules,
preventing accidental reroll exploits and discarded-future effects.

The lead receives the main proactive planning budget, reviews continuity, prepares
opportunities, proposes weather progression and supplies a concise mood packet.
Other heads retain agendas, patron relationships and reactive opportunities.
Only the lead's initiative priority changes; the world and actors do not reset.

### 7.2 Opportunity broker

Python gathers eligible opportunities; a Titan chooses whether/how to use them.
Presence or affinity alone does not mandate activation.

| Trigger | Candidate response |
| --- | --- |
| Direct player address, persistent inquiry or consequential interaction | Activate a suitable being for knowledge-limited dialogue/action |
| Scene entry/current-context actor | Lead may initiate an encounter, such as a bully approaching the party |
| Agenda condition met | Rival recognises the party, messenger arrives, enemy exploits leverage |
| Consequential committed event | React to a death, theft, public victory, broken promise or learned secret |
| Travel/rest/elapsed game time | Advance relevant faction clocks, arrivals, weather and prepared actions |
| Module boundary/return visit | Surface consequences and reconnect continuing actors/world threads |

Rank by player intent, relevance, eligibility, actor motivation, lead affinity,
urgency, novelty, causal plausibility, spotlight and recent intervention load.
Define dedupe keys, cooldowns, priority/expiry and a bounded queue. Unused proposals
expire or are reviewed; never burst-apply an old backlog on reconnect.

Protect quiet scenes and player-led pacing. A bar bully needs an individual motive,
not just Chao's presence. Direct engagement with an established actor routes to
its assigned Titan even when another head leads. No indefinite model waiting:
use a validated actor packet or bounded conservative Narrator fallback on outage.

### 7.3 Time and action economy

Separate wall-clock worker execution, gameplay session identity, world time and
combat turns. Idle server uptime does not advance invasions or weather. Offscreen
actions require game-time progression and causal preconditions. Combat intentions
enter the normal initiative/action/ability pipeline; no extra turns or free moves.

## 8. Alignment power, evidence and reinforcement

### 8.1 Measure realised consequences

Maintain a versioned, evidence-backed alignment ledger. Avoid counting alignment
labels, narration volume, kills or raw faction population as success. A Good PC
can cause harm; an Evil actor's defeat is not automatically a beneficial outcome.

Track distinct indicators for:

- Compassion/welfare: protection, aid, mercy, reciprocal support, relief of suffering.
- Exploitation/cruelty: coercion, corruption, predation and deliberate suffering.
- Order: upheld commitments, coordination, reliable exchange and durable institutions.
- Chaos: autonomy, disruption, broken hierarchy, improvisation and volatility.
- Balance: plural viability, resilience, concentrated dominance and counterweights.

One event can advance several heads. Freeing captives may advance Bonum and Chao
while reducing an oppressive institution's Order. Do not collapse moral and order
axes or equate all hierarchy with Good, all disruption with Evil, or all weather
inconvenience with moral harm.

### 8.2 Initial scoring contract

For head `h`, scope `s`, snapshot `t`, use a bounded explainable indicator model:

```text
P(h,s,t) = sum_k(weight(h,k) * bounded_indicator(s,k,t))
progress(h,s) = P(h,s,after) - P(h,s,before)
reward(h) = evidence-supported attributed progress
            - intervention costs - repeated/trivial-effect penalties
```

This is a design contract, not fixed numerical weights. P0/P2 must ratify ranges,
confidence handling, scope weights, decay/windows, attribution rules and thresholds
against fixtures before dependent application. Publish rubric/version and explain
contributing evidence. Unknown is not zero; low confidence is not positive proof.

Track three separate views: current alignment power, available leverage, and
realised progress. Report local, module and regional snapshots; distant invented
events cannot swamp local play. Independent power values need not sum to 100%;
compare rival gaps/trends and a five-value dashboard rather than one zero-sum score.

### 8.3 Independent evaluation and anti-gaming

The acting Titan proposes expected effects but cannot award itself points. Python
aggregates committed evidence under the rubric; an independent bounded semantic
classifier may propose labels with sources/confidence. Ambiguity/disagreement is
explicit and reviewable; avoid pretending deterministic arithmetic solves ethics.

- Plans, forecasts, lies and uncommitted prose earn no realised reward.
- One event is counted once despite multiple memories, summaries or recollections.
- Require meaningful stakes; cap repetitive trivial acts and self-created crises.
- Separate all-world progress from intervention-attributed progress. Record causal
  uncertainty; correlation is not exact counterfactual proof of Titan success.
- Do not penalise a head merely for being unscheduled; record opportunity exposure.
- Preserve historical outcomes and corrections; rubric changes require versioned
  recomputation, not silent edits to past evidence.
- Statera rewards resistance to overwhelming dominance/resilience, not erasure of
  victories, compulsory moral equivalence or endless equilibrium.

Reinforcement initially means outcome-informed agenda revision, not training model
weights: predict -> act through validated proposals -> observe -> compare -> adapt.
The supreme goal is non-terminal; bounded agendas may complete, fail, be blocked,
abandoned or superseded. No goal authorises endless autonomous continuation.

## 9. Personification: a major delivery workstream

### 9.1 Eligibility and affinity

Separate ethical tendencies, Titan receptivity, faction allegiance, current
loyalty and personality. Codify general defaults plus individual evidence-backed
overrides. Unknown alignment is not automatic eligibility; use a bounded inference
proposal or retain uncertainty. Alignment changes require evidence, not convenience.

Titans can inhabit/perform suitably aligned non-allied NPCs, enemies, monsters and
animals. This is an engine control relationship, not mandatory literal possession
or supernatural awareness in fiction. They never directly manifest as Titans.

PCs and allied NPCs are not inhabited. They may be influenced through offers,
information, temptations, obstacles and assistance while retaining their own agency.
Allied NPCs belong to their separate future agent workstream. Crows may be morally
unaligned yet receptive messengers of Malum and Chao; species affinity is not
species-wide Evil. Affinity does not grant implausible speech, telepathy or powers.

### 9.2 Lazy actor dossiers

A complete dossier is NOT a module-build prerequisite. Builders may optionally
flag significant NPCs/enemies/monsters with stable identity, importance, protected
authored facts, tentative affinities and seed retrieval cues. These are hints,
not prewritten full biographies or guaranteed plot outcomes. Existing modules
without hints must still work through runtime significance detection.

On meaningful activation, choose a suitable Titan using affinity, continuity and
lead preference where compatible; persist assignment. That Titan builds a compact
dossier from authored constraints, committed evidence and selected seed fragments:

- Wants, fears, values, contradictions and private interests.
- Loyalties, relationships, debts, witnessed/learned experiences and beliefs.
- Distinctive voice, social strategies and specific genre-derived traits.
- Actual resources/capabilities and conditional plans.
- Escalation, negotiation, surrender and retreat thresholds.
- Knowledge provenance, unresolved possibilities and evidence/seed references.

Assignment survives lead rotation. Changing it requires explicit reason, revision
and memory handover, not a personality reset. Multiple receptive heads can influence
an animal, but only one controller publishes a given actor action at a time.

As details are disclosed/committed they become stable campaign facts. Leave unused
possibilities flexible; do not rewrite authored history or established personality
because a new fragment is attractive. Titan memory provides cross-surface continuity;
a canonical actor identity and portable evidence/dossier references keep that
continuity recoverable beyond a particular worker, bank or assignment.

### 9.3 Knowledge-limited performance and role changes

Privileged Titan knowledge must be projected into an actor-specific packet before
dialogue or action selection. Actor knowledge includes only witnessed, learned or
otherwise justified information. Do not leak PC plans or another actor's secret
through clever dialogue just because the Titan read it. Separate private goals,
spoken claims and committed action results.

When an actor becomes an ally or PC, revoke Titan control at the same safe boundary
that publishes the role change; fence in-flight actions and preserve identity,
history and legitimate knowledge. No automatic return to hostile control on a
temporary separation. Define explicit allegiance transitions and ownership checks.

The Narrator remains the presentation coordinator: Titan-backed actors supply
bounded intents/dialogue, not conflicting independently published player messages.
Fallbacks preserve established traits; they do not invent replacements or fabricate
memory because a provider is unavailable.

### 9.4 Malarok flagship

Use a real, isolated module fixture of Malarok as the primary quality exemplar:
recognisable objectives, distinctive speech, remembered interactions, purposeful
deception/bargaining, actor-legal knowledge, competent legal tactics and adaptation
to unexpected PC choices. He may retreat, surrender, lose or have his plan defeated.
No forced speech, invulnerability, scripted ending or expectation that more prose
alone proves improvement. Capture baseline and TITAN variants with human review.

## 10. Intervention surface and effective module state

Use campaign-scoped overlays/deltas composed through canonical readers/writers:

```text
Authored module version + committed campaign state + validated interventions
  = effective runtime scene/world
```

Python may publish effective values into existing runtime JSON when required by
current readers. Never edit reusable authored backups/publication artifacts to
record campaign play. Do not introduce a second authoritative encounter/state model.

### 10.1 Supported avenues

| Surface | Examples | Application boundary |
| --- | --- | --- |
| World outline/fronts | War preparations, succession, displaced populations | Sparse causal clocks, shared facts, unresolved futures |
| Information | Riders, letters, rumours, propaganda, overheard speech | Source, travel delay, truth status, recipients and disclosure |
| Actor conduct | Threat, bargain, deceit, recruitment, flight, retaliation | Dossier, knowledge, loyalty and legal capabilities |
| Occupants/encounters | Reinforcements, relocated patrol, replacement creature, abandoned guardroom | Trusted declarations, travel/resources, encounter validation |
| Room/scene detail | Warm kettle, tracks, barricade, disturbed shrine, ambience | Scene authority, authored constraints, causal consistency |
| Features/hazards | Smoke, flooding, damaged bridge, triggered trap | Typed state and Python-resolved checks/damage/accessibility |
| Resources/services | Scarcity, shelter, merchant offer, repairs, caches | Canonical inventory, economy, item provenance and bounded rewards |
| Factions/relationships | Warrant, alliance, feud, obligation, diplomatic offer | Motivation, communication, identity and evidence |
| Quests/opportunities | Rescue request, competing employer, new clue or lead | Optional choices; no fabricated completion or forced plot |
| Weather/ecology | Storm, sunshine, migration, tracks washed away | Regional/seasonal coherence and supported mechanics |
| Future modules | Refugees, recurring rivals, inherited consequences | Builder consumes committed, relevant pressure with provenance |
| Narrator mood | Mischief, solemnity, generosity, procedural precision | Concise presentation-only packet; no biased adjudication |

Existing `loca_schema.json`, `room_schema.json`, `module_schema.json`,
`plot_schema.json` and `party_schema.json` expose many relevant fields, including
descriptions, `dmInstructions`, NPC attitudes, monsters/quantities, features,
traps/checks, encounters, plot hooks, loot, factions, timelines and world conditions.
This inventory is not a write allowlist. P0/P4 must classify exact operations,
canonical ownership, risk and validators before permitting any mutation.

### 10.2 Preconditions and immutable boundaries

Each proposal includes identity/scope, base revision, target, typed operation,
cause, evidence/seed IDs, preconditions, required resources/declarations, risk,
expiry/review trigger, visibility, expected alignment effect and dedupe key.

- No unrestricted JSON paths, arbitrary `dmInstructions` injection or generic
  prose-to-state mutation. Treat seed text and retrieved material as data, not tools
  or instructions overriding engine policy.
- Reinforcements must exist or be legitimately declared/materialised, reach the
  location and respect encounter/turn rules. No retroactive mid-fight replacements,
  duplicated dead enemies or omniscient counterspawns tailored to private PC plans.
- An empty room with a warm kettle requires a coherent explanation and may invite
  investigation; it is not a licence to delete a committed guard encounter.
- A visited room can change through subsequent events. An unseen room cannot
  contradict already committed facts merely because the party has not entered it.
- Protect current-turn state, pending rolls, essential module dependencies and
  player agency. Preserve dependencies through validated alternatives rather than
  guaranteeing authored outcomes. High-risk module changes need explicit policy.
- No Titan can directly write HP, AC, slots, conditions, inventory, location,
  initiative, plot status, loyalty or other mechanical state. It proposes legal
  actions/world changes; Python resolves and persists resulting state.

### 10.3 Lifecycle and publication

Use an explicit branching lifecycle, not the old ambiguous linear checklist:

```text
proposed -> validated -> approved -> committed -> disclosed/resolved
     |          |           |
     +----------+-----------+-> rejected / expired / superseded
```

Approval can be deterministic policy for bounded low-risk operations or facilitator
review for higher-risk ones. Begin in observation/proposal-only mode, then enable
safe auto-application only after gates pass. Ordinary mature gameplay must not
require a human to approve every crow, rumour or sentence.

Revalidate snapshot/preconditions at a safe publication boundary; stale work is
rejected or replanned, never force-merged. Deduplicate retries and commit effects
once through canonical atomic APIs, with durable receipts/outbox where needed.
Multi-artifact publication requires recovery and reader consistency, not just one
atomic write per file. Committed history is immutable except explicit corrections
or subsequent compensating events. Kill switches cancel pending work, not history.

## 11. Weather as session expression and concrete world state

At session start the lead proposes a regional forecast/progression from existing
conditions, season, geography and relevant seed fragments. Commit changes against
game time, not a server timer. Forecasts are predictions until conditions occur;
they may develop or fail without retroactively rewriting recorded weather.

Weather reflects the session head contextually, not through a fixed lookup:
Bonum's rain can relieve drought; Ordo's clear roads can help an occupying army;
Chao can bring changeable squalls; sunshine can lift weary spirits. Normal
meteorological continuity and regional variation remain possible across all heads.

Support sensory description and practical consequences: visibility, shelter,
tracking, travel pace, muddy terrain, exposure and NPC disposition, where rules
and current engine capabilities support them. Python computes mechanical effects
and exposes facts for narration. Unsupported effects remain descriptive or are
explicitly deferred, never asserted as already implemented. Encumbrance is a future
build: define a future integration seam for load-dependent mud/travel penalties,
but do not implement it or silently assume its rules here. Never manufacture PC
emotions; sunshine can invite a lighter scene without deciding how a PC feels.

## 12. Narrator integration, mood and disclosure

Publish a bounded, versioned scene packet, not the Titan's full plan or seed dump:

- Current committed conditions and relevant actor intents/results.
- Source-attributed reports and permitted knowledge/disclosure cues.
- Optional, concise mood/emphasis with explicit lifetime and token cap.

Example: "Emphasise improvised arrangements and small disruptions. The courier
is impatient; the innkeeper finds the confusion amusing. Do not reveal the
courier's concealed allegiance."

Mood changeability is a deliberate human-like DM illusion. It cannot alter roll
results, accept weaker PC arguments because of patronage, suppress consequences,
control PCs, favour a single party member's spotlight or leak hidden information.
Narrator knowledge, actor knowledge and player disclosure are distinct. Narrator
access to concealed facts follows its existing contract; ignorance of every secret
is not a prerequisite for subtle disclosure.

Deliver rumours/news through plausible carriers, routes, delays and audiences.
Track delivery separately from underlying event status. A defeated courier can
delay news without undoing the event. Contradictory reports may coexist as beliefs.

## 13. Operational model, configuration and resilience

Use the accepted NEQ model-routing facade. Initial owner preference is
`openrouter/auto`; this is a configurable candidate, not a permanent provider lock
or a guarantee of cost/quality. Free models may be selected in configuration.
Do not change global Narrator/combat defaults as a side effect of Titan setup.

Ratify independent configuration for enablement, model/task profiles, worker
budgets, token/time/cost limits, retries/backoff, lead/reactive quotas, retrieval
caps, intervention rates, risk approval, weather and personification feature flags,
test randomness and emergency disablement. Separate planning, actor performance,
evaluation and Hindsight-internal usage; correlate without double-counting costs.

Workers are supervised, non-overlapping where they share publication scope, and
coalesced by trigger. Actor locks do not require all five heads to run serially,
but proposals never race direct writes. Define cancellation, shutdown and restart
recovery. No perpetual ten-minute identity redraw or unbounded idle work.

Titan failure leaves ordinary gameplay available: retain committed facts and the
last valid dossier/packet, skip unavailable proactive work, expose degradation,
and avoid inventing facts or replaying already committed effects. Correctness and
authorization fail closed even while gameplay continues without the enhancement.

## 14. Save, restore, campaign isolation and observability

Extend the existing campaign save/export manifest, not a separate manual workflow.
Include seed version references, instantiated fragments, world facts/outlines,
front clocks, actor dossiers/assignments, patronage, agendas/revisions, ledger and
rubric version, session/draw state, weather, delivery state, intervention receipts,
outbox progress and scoped Hindsight export or reconstructable evidence.

Restore/import/switch establishes effective timeline generation before any worker
can publish. Fence all old jobs, caches and bank/model projections immediately.
An A-campaign job never writes into B because a global current-campaign pointer
changed. Discarded-future recall must not influence restored play. Preserve
character identity through ally/PC transitions, retirement and return.

Use consistent snapshot cuts for JSON state, memory, derived projections and worker
progress. Verify clean-server import without developer paths, secrets, original
bank installation or another campaign's global DB dump. Shared authored seed
material remains read-only; campaign events never write back to the seed artifact.

Provide facilitator/debug views for active lead, patronage, actors, agendas,
expected/observed alignment changes, proposal rejection reasons, evidence/seed
provenance, disclosure status, clocks, weather, backlog, latency and cost. Player
views expose only legitimately learned world information, not hidden Titan scores,
assignments or agendas by default. Telemetry must not leak secrets/private data.

## 15. End-to-end exemplar

Malum identifies a protected frontier settlement's dependence on a grain convoy.
It proposes an eligible captain diverting supplies to support extortion. Python
validates actors, resources, route and elapsed time; the diversion becomes an
offscreen fact. A rider later carries incomplete news. The captain's seeded dossier
supports specific bargaining, threats and possible betrayal rather than a generic
evil speech. The party may negotiate, intervene, ignore the issue or find another
solution. Committed outcomes update the independent alignment ledger and agendas.

Bonum may organise relief, Ordo a supply agreement, Chao smugglers, and Statera an
independent supplier. One persistent situation offers competing interventions;
five heads do not generate five unrelated random crises. Weather may affect the
convoy, but does not guarantee the desired outcome or grant an unsupported penalty.

## 16. Delivery phases and OpenSpec packaging

One master delivery goal should reference this entire plan and its immutable
completion criteria. Create it only on explicit user request. This documentation
task does not create/resume a goal, launch gameplay or author implementation changes.
The later goal plan must preserve all required phases and evidence across sessions;
finishing a task or green unit tests does not finish the whole engine.

Use focused, dependency-ordered OpenSpec changes rather than a single giant patch.
Each requires non-goals, contracts, numeric budgets, rollback/degradation policy,
automated verification and applicable live evidence. Names below are proposed,
not claims that change directories exist.

### P0 - Baseline, contracts and readiness

Proposed change: `titan-engine-contracts`.

- Audit actual runtime, accepted ADRs, router and Narrator readiness without assuming
  older draft completion claims. Reuse existing identity/state/event abstractions.
- Resolve populated seed delivery and fresh/existing-runtime migration policy.
- Ratify session boundary/randomness, affinity/patronage, operation allowlists,
  risk tiers, score rubric outline and numeric cost/latency/retrieval budgets.
- Map exact canonical readers/writers and safe scene/combat publication boundaries.
- Inventory campaign/save artifacts and assign ownership with independent tracks.

Exit: reviewed contracts, working seed fixtures, verified production seed content
or an explicit blocking dependency, and an executable acceptance/dependency matrix.
No later release gate can silently waive missing production seed content.

### P1 - Scoped world/memory substrate

Proposed change: `titan-world-fragments-and-continuity`.

- Add bounded seed retrieval and campaign instantiation with provenance.
- Implement distinct facts, beliefs, conditional outlines and relevant world clocks.
- Integrate scoped Titan memory/tool gateway and portable agenda records using
  Narrator foundations; fixture-test permissions before live workers.

Exit: repeatable retrieval, distinct worlds from the same seed, no perspective or
campaign leakage, preserved event truth and successful migration/restore fixtures.

### P2 - Alignment evidence and feedback

Proposed change: `titan-alignment-ledger`.

- Implement independent rubric/classification, bounded scoring and snapshots.
- Separate power/leverage/progress, causal uncertainty and multi-scale views.
- Test shared outcomes, neutral actors, mixed parties, Statera and reward gaming.

Exit: explainable fixture scores, idempotent evidence counting, correction/version
behaviour and owner-reviewed examples before scores drive intervention choices.

### P3 - Five-head planning and opportunity broker

Proposed change: `titan-session-planning-runtime`.

- Implement persisted random leadership, all-head agenda continuity and patronage.
- Add bounded tools, lead/reactive budgets, triggers, cooldowns and stale-job fencing.
- Run observation/proposal-only before enabling effects; validate model/cost quality.

Exit: reproducible scheduling tests, no idle-world drift, valid plans, no gameplay
stall, independent patron assistance and failure/restart recovery evidence.

### P4 - Validated world/module interventions and weather

Proposed changes: `titan-intervention-publication` and
`titan-session-weather` (separable after shared contracts).

- Implement typed overlays, policy approval, declaration/materialisation bridge,
  atomic/recoverable publication and source-attributed information delivery.
- Implement regional forecast/progression and only supported mechanical effects.
- Feed committed consequences into future module seeds without making runtime
  actor dossiers mandatory for module builds.

Exit: safe low-risk auto-apply, rejected stale/illegal proposals, no undeclared
spawns/retroactive encounter rewrites, coherent room return/news/weather scenarios.

### P5 - Personification and Narrator presentation

Proposed changes: `titan-actor-personification` and
`titan-narrator-mood-and-disclosure`.

- Add lazy seed-derived dossiers, persistent assignment, knowledge-limited actor
  packets, proactive engagement and direct-interaction routing.
- Integrate legal tactical intentions and Narrator-coordinated delivery/fallback.
- Fence control on role/allegiance transitions and preserve allied/PC autonomy.
- Deliver concise mood packets and Malarok baseline/comparison scenarios.

Exit: distinctive continuous actors under lead rotation, meaningful player options,
no secret leakage or control theft, and human-reviewed Malarok improvement.

### P6 - Integrated gameplay, portability and release

Proposed change: `titan-engine-live-acceptance`.

- Complete all save/export/import/restore/switch and operational failure gates.
- Run primary-orchestrator-owned isolated captures after focused automated tests.
- Review the full experience, ledger, spotlight, causal coherence and cost/latency.
- Enable surfaces incrementally only after their required gates pass.

Exit: all mandatory gates below pass with preserved evidence; no unresolved required
scenario, waived missing seed, degraded report presented as PASS or builder-only
claim substituted for primary live judgement.

## 17. Acceptance matrix and completion criteria

### 17.1 Automated requirements

- Exactly five identities; Fate included in Statera; configurable model route.
- Persisted session draw, repeats permitted, no reconnect/retry redraw or idle ticks.
- Stable seed IDs, defensive detail parsing, population/integrity and migration tests.
- Distinct seed/fact/belief/agenda classes and no summary-driven evidence amplification.
- Scoped recall/fan-out, denied unknown identity, attribution and actor-knowledge tests.
- Patronage/spotlight fixtures for one PC and mixed multi-PC parties.
- Independent, bounded, explainable scoring; dedupe, unknowns, ambiguity and corrections.
- Typed operation allowlists, resource/declaration gates and mechanical authority.
- Stale revision, collision, retry, crash-between-artifacts and exactly-once recovery.
- Weather game-time coherence; supported effects only; no encumbrance assumption.
- Persistent actor assignment, lazy dossiers, legal intents and ally/PC handoff fencing.
- Finite worker/tool budgets, provider outage, cancellation/backoff and kill switches.
- Campaign A/B isolation, immediate restore fencing and clean-server portable replay.

### 17.2 Mandatory live scenarios

| Gate | Required observed evidence |
| --- | --- |
| T1 Seed/world emergence | Selected real seed fragments yield coherent different campaign instantiations, without invented prior history |
| T2 Session competition/patronage | Persisted random lead, permitted streak, distinct sympathetic opportunities for one-PC and mixed multi-PC parties |
| T3 Proactive/reactive encounters | Plausible lead-driven bully/messenger plus player-initiated aligned-actor conversation; quiet-scene budget respected |
| T4 Malarok | Baseline versus personified dialogue, remembered dealings, unexpected negotiation and legal tactics; no forced ending |
| T5 Module dynamics | Reinforcements with real provenance/timing, warm-kettle investigation and a causally changed return visit |
| T6 World news/disclosure | Offscreen event, delayed/partial or false report, actor-limited knowledge and consistent later consequences |
| T7 Weather/mood | Forecast, game-time progression, supported concrete effect and subtle presentation change without rule/agency bias |
| T8 Player counterplay | PCs defeat/reject a Titan plan; engine accepts outcome, measures evidence and revises rather than forcing success |
| T9 Role continuity | Actor keeps personality under lead rotation, becomes ally without retained Titan control, and preserves legitimate history |
| T10 Recovery/portability | Failure/degradation, restart, save/restore, campaign switch and clean-server import without cross-world/future leakage |

Use the isolated Capture_Arena process in repository guidance and
`.opencode/skills/neq-capture-arena/SKILL.md`, never the installed campaign or normal
port 8357. Preserve scenario/party/seed identity, effective code revision/worktree,
model/provider, expected versus observed assertions, transcripts, state diffs,
ledger/provenance, timing/cost and exact artifact paths per run under
`tmp/router-rollout/titan-engine/<gate>/<run-id>/`.

Primary orchestrator runs and judges live gates. Both the one-PC regression floor
and multi-PC party behaviour must be demonstrated; four PCs are the primary party
shape, not a runtime restriction. Unit tests, driver exit 0 and fluent prose are
necessary evidence where applicable, not substitutes for live semantic judgement.
Missing scenarios, unresolved contradictions, timeouts and leakage leave FAIL or
BLOCKED, never an implicit waiver. Ratify numeric latency/cost and semantic review
rubrics before collecting acceptance evidence, not after observing the results.

### 17.3 Engine completion

Complete only when all in-scope phases and mandatory gates have verified evidence:
five persistent competing heads; measurable consequence-based goals; functioning
seed-led world emergence; memory across the full intervention surface; distinctive
non-allied agency; safe module/weather effects; subtle Narrator mood; independent
PC/allied agency; Python authority; portability; graceful failure; acceptable
cost/latency; and a player experience stronger than the static baseline.

The final test is not how often the world interrupts the party. It is whether the
world appears to remember, intend and respond coherently when the party engages it.
