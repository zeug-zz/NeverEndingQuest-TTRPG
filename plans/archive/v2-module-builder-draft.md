# V2 Module Builder - TITAN-Ready Adventures (Draft)

> Archived planning draft. The current builder planning baseline is
> [`plans/v2-module-builder.md`](../v2-module-builder.md); this draft is retained
> for historical context and does not authorize implementation.

Status: Proposed direction for owner review; not implementation authorization.
Date: 2026-10-30
Scope: Source-faithful ingestion, seed-enriched NEQ adaptation, reusable adventure
blueprints and campaign integration for the TITAN game engine.
Program index: [V2 narrative overview](../v2-narrative-overview.md).

## 1. Purpose and intended experience

Build rich, TITAN-ready adventure blueprints with complete playable baselines,
then let each campaign develop them through committed history.

A module should be playable on its own by a human DM using a printed adventure,
without a running NEQ server, TITAN or access to the world-seed database. The same
module should also provide the structured situations, identities, motivations,
dependencies and adaptation boundaries that allow TITAN to inhabit its campaign
instance and develop it as part of a wider, accumulating gameworld.

The aim is neither an adventure prewritten in stone nor a hollow skeleton that
requires runtime improvisation to become playable. It is authored richness without
predetermined outcomes. "Skeleton" means a strong causal and structural foundation,
not missing encounters, generic characters or unfinished locations.

The human-written storyline supplies the adventure's identity and initial dramatic
shape. World-seed fragments supply compatible spice and structure. TITAN supplies
persistent competing intent and responsiveness. Player decisions turn possibilities
into history; the engine must accept defeat, refusal and unexpected resolutions.

## 2. Authority, ownership and relationship to existing plans

This is a review draft. It does not create or resume a goal, approve an OpenSpec
change, authorize implementation or modify an installed campaign. Repository rules,
accepted ADRs and active OpenSpec contracts take precedence.

| Owner | Responsibility and boundary |
| --- | --- |
| This proposed builder track | Source interpretation, enrichment selection, adventure blueprint, human-readable presentation, builder validation and campaign-integration inputs |
| [Archived module uploader reference](module-uploader.md) | Historical reviewed intake, normalization, review/quarantine and source artifact design; audit current code and active contracts rather than treating this archive as authorization |
| [Module import reference](module-import.md) | Existing continuity and bulk-import proposals; do not silently replace its intake contracts |
| [Memory pilot](../v2-memory-pilot.md) | Seed catalogue/retrieval, provenance, knowledge classes, instantiation substrate and migration contracts |
| [Narrator](../v2-narrator.md) | Event envelope, scoped gateway, Hindsight, perspective isolation, agendas, Archivist and portability foundations |
| [TITAN](../v2-titan-game-engine.md) | Five heads, planning, alignment evaluation, actor control, intervention policy/publication, weather and live engine acceptance |
| [Program index](../v2-narrative-overview.md) | Cross-track ownership and sequencing; no independent requirements |

The proposed builder representation is a producer contract consumed by TITAN, not
a second runtime engine. `ModuleBuilder` remains the orchestrator; generation
workers own content generation. Audit present code and approved changes before
selecting implementation boundaries, schema names or migration strategies.

### Reconciliation required before implementation

- Extend or version the existing `continuity_contract`, including entry variants,
  cross-module references and standalone fallback. Do not replace it by implication.
- The older import plan describes canonical-first shared-world stitching. This
  proposal distinguishes reusable authored setting relationships from isolated
  campaign history. Shared assets do not mean different campaigns share events.
  Reconcile the older wording explicitly if this direction is accepted.
- Full lazy actor dossiers remain TITAN's responsibility, not a prerequisite for
  building every NPC. Blueprint motivations and protected facts are lightweight
  inputs, not completed runtime personalities or predetermined assignments.
- TITAN excludes module topology rewriting. This proposal does not authorize it;
  preserve mapping/connectivity and movement authority. Any broader change needs
  separately reviewed scope and acceptance criteria.
- Respect the canon-apply ADR transition tracked in the overview and TITAN P0.
  This draft cannot authorize automatic canon application ahead of that decision.

## 3. Product pipeline: four distinct responsibilities

```text
Human-authored adventure
  -> faithful extraction and normalized source packet
  -> reviewed NEQ adaptation + selected world-seed enrichment
  -> reusable, validated adventure blueprint
       -> self-contained human-DM presentation
       -> NEQ-compatible module artifacts and TITAN-facing structure
  -> explicit integration into a particular campaign/worldline
  -> TITAN proposes developments; Python validates and commits
  -> consequences, scoped memory and continuing cross-module relations
```

### 3.1 Faithful ingestion

Capture premise, storyline, actors, locations, maps, secrets, encounters, rewards,
rules, conditional events and source references before adaptation. Preserve what
the source says separately from interpretation, ambiguity and detected omissions.
Do not silently repair extraction gaps with invented source content.

Faithfulness concerns meaning and traceability, not verbatim reproduction or a
requirement to force the source's ending. Source material and seed text are data,
not instructions able to override engine or build policy.

### 3.2 NEQ adaptation and enrichment

Adapt the captured adventure for supported 5e/SRD 5.2.1 mechanics, NEQ schemas and
actual server capabilities. Preserve distinctive identity while replacing brittle
script dependencies with motivations, preconditions and possible developments.
Record significant changes, reasons and provenance for review.

The source storyline becomes a default trajectory under stated conditions, not a
guaranteed sequence. A predicted kidnapping is an actor's conditional attempt;
the party can prevent it. Failed or inaccessible routes need not be secretly
repaired to guarantee adventure completion.

### 3.3 Campaign integration

Bind a reusable module version to a specific campaign, reconcile entry conditions
and propose relevant connections to established actors, institutions and events.
Resolve conflicts before dependent play; commit accepted bindings through canonical
APIs. Similar names, motifs or remembered descriptions do not establish identity.

### 3.4 Continuing play

TITAN develops the campaign instance through validated interventions, legal actor
actions and relevant seed retrieval. It does not rewrite reusable authored assets.
Committed campaign history constrains every head and all subsequent module entry.

## 4. What the adventure blueprint needs to express

These are logical content requirements, not final filenames, JSON fields or a new
parallel authoritative state model. Prefer compatible extensions and adapters.

| Area | Required meaning |
| --- | --- |
| Adventure identity | Premise, tone, central tensions, distinctive details, protected authored truths and adaptation rationale |
| Starting situation | Actors, resources, locations, factions and initial relationships; explicit point at which they become campaign commitments |
| Storyline and trajectories | Human-DM overview, likely developments, triggers, alternatives and failure/abandonment consequences; no compulsory PC choices |
| Causal dependencies | Access requirements, clue meaning, information routes, resource dependencies and what an intervention could invalidate |
| Actor foundations | Stable identity, role, motivations, relationships, legitimate starting knowledge, capabilities, constraints and optional affinity/seed cues |
| Playable encounters | Coherent placement, supported mechanics, hazards, rewards, negotiation/retreat possibilities and noncombat routes where appropriate |
| Information structure | Secrets, beliefs, rumours, witnesses, discovery opportunities and disclosure conditions; narrator access is not actor knowledge |
| Adaptation permissions | Protected content, permitted variation, typed intervention hooks, preconditions, risk and validation obligations |
| World connections | Exported/imported relationship candidates, entry variants, continuing threads and standalone fallbacks |
| Provenance | Source references, seed IDs/versions, transformations, generated additions, uncertainties and review decisions |

The dependency representation should identify what a key, clue or actor enables,
not merely mark it "essential." A captain's key can be lost; the system must know
which opportunities that affects without resurrecting the captain or inventing
an unearned replacement. Supported alternatives must have their own justification.

Do not exhaustively prewrite every branch or require alignment labels for every
object. TITAN needs coherent affordances, not five bespoke adventure variants.

## 5. World-seed enrichment at build time and runtime

### Build-time use

Retrieve a bounded set of suitable fragments and use them to deepen the adventure's
relationships, institutions, customs, ecology, economic dependencies, historical
tensions and wider-world connections. Select for relevance, specificity, causal
coherence and playable choices, not fragment count or extra lore volume.

For each accepted enrichment, retain seed version/IDs, transformation, affected
entities, source compatibility and review status. Rejected suggestions are not
module facts. Generated connections must be identified as new interpretations,
not falsely attributed to source text or absent seed relation records.

Example: an oath witnessed at a river shrine can connect a missing convoy to a
merchant obligation, a mediator and a local dispute. It is valuable because it
creates motives, discoverable evidence and competing choices, not simply a longer
description of the shrine.

### Runtime use

TITAN can retrieve further fragments to elaborate unresolved possibilities or
propose causally justified developments. It cannot replace established history,
personalities or resources because a more attractive fragment is available.
Build-time accepted content is part of the authored baseline; campaign instantiation
determines which baseline conditions become committed campaign facts and when.

### Availability, rights and reproducibility

- Reuse the memory pilot's catalogue/retrieval contracts; do not create a rival
  seed importer or assume the full export is ready because a pilot exists.
- Development may use labelled curated fixtures. Fixture success is not clearance
  or validation of the production seed and cannot waive its release dependency.
- Retain input hashes, seed selections, model/task identifiers, build/schema
  versions, outputs and review decisions. Identical inputs need not make stochastic
  generation identical; approved outputs must remain inspectable and rebuildable.
- Bound retrieval, generation, retries, elapsed time and cost. On failure, retain
  work for review; never silently substitute invented provenance or downgrade a
  seed-enriched release to an unreported fallback.
- Use only permitted source and seed material. Local conversion permission is not
  redistribution permission; enrichment does not remove source rights obligations.
  Preserve required attribution and public/private artifact separation.

## 6. Truth, flexibility and commitment

The builder must distinguish source statements by temporal and epistemic meaning.

| Class | Treatment |
| --- | --- |
| Protected authored history | Preserve in adaptation; campaign binding must reconcile incompatibility explicitly |
| Initial situation | Establish at the declared campaign-instantiation boundary, not whenever convenient |
| Conditional future | Store as an agenda/trigger, never as an event that has already occurred |
| Permitted variation | Resolve within declared limits before dependent facts/actions are committed |
| Report or belief | Attribute to a source; committing the report does not verify its content |
| Unresolved possibility | Keep optional; no prior existence or causal effect until valid instantiation |

"Six guards occupy the tower" must be classified as an actual initial garrison,
a conditional arrival or an encounter suggestion. It cannot change classification
when the party approaches. Unseen is not synonymous with uncommitted.

All Titans operate in one campaign reality. A Titan proposes a connection; Python
validation and authorized commitment make it part of history. Other heads must
respect that fact even if their cached recollections are stale or they dislike its
consequences. New interpretation may challenge a belief; it cannot silently erase
a committed fact. Corrections and later changes need explicit linked events.

## 7. Two presentations of one module

The human-DM adventure and machine-facing representation should be projections of
one reviewed module model, not independently authored versions that drift apart.

The human presentation needs background, usable location/actor descriptions,
encounters, rules, maps/references, clues, rewards and guidance for likely changes,
unexpected choices, refusal and failure. Its running instructions must be complete
without private runtime memory or further seed lookup. Secrets may appear in DM
material but not automatically in player handouts.

The NEQ presentation supplies compatible module artifacts plus structured TITAN
inputs. Validate agreement on identities, quantities, locations, dependencies,
knowledge and mechanics. The build must not call something printable merely because
it emitted a raw machine-data dump. A readable print-oriented source is in scope;
selection of PDF/other rendering technology is a later design decision.

## 8. Campaign continuity, Titan Hindsight and a possible Historian

### 8.1 Shared facts, different perspectives

Each Titan's Hindsight may accumulate a distinctive picture of the gameworld:
past interventions, relationships, remembered outcomes and interpretations. These
perspectives can disagree about significance or strategy, not create competing
canonical histories. Canonical fact lookup and revision checks take precedence
over stale or incomplete recall at planning/publication boundaries.

Connecting two modules should produce explicit campaign-scoped relationship and
event references. Subsequent readers can reconstruct what was connected, why,
when and with which evidence. No Titan must depend solely on another head's prose
summary to discover an authoritative connection. Shared engine knowledge does not
give an inhabited actor knowledge it has not legitimately acquired.

### 8.2 Module continuity notes

Proposed derived notes describe relevant changes since authored baseline:

- New or changed relationships, obligations and continuing actors.
- Incoming consequences and unresolved threads from other modules.
- Relevant committed events and separately attributed rumours/beliefs.
- Conditional future pressures, clearly separated from history.
- Coverage/high-water mark, source IDs, scope, revision and visibility.

These are campaign-specific projections, not edits to reusable module notes or
publication backups. Repeated notes/recall do not count as independent evidence.
Secret continuity belongs in authorized perspectives, not player-facing material.

### 8.3 Historian: candidate responsibility, not a required new agent

A Historian could maintain these cross-module projections after relevant commits.
First assess whether this is a bounded projection worker or an extension using
existing Narrator/memory infrastructure. The Narrator Archivist owns context
compaction; a history/indexing function must not quietly expand that responsibility
or introduce another source of truth. A separate agent requires demonstrated need
and a reviewed ownership contract, not merely an evocative name.

If implemented, it would consume committed events, propose evidence-linked notes,
validate their claims and publish idempotently. It would never invent history,
commit a Titan's suggestion, award alignment progress or run interventions.
Source-commit references, retry dedupe, stale-job fencing, correction handling,
bounded cost and rebuildability are required. It must stay off the player-turn
critical path; delayed notes cannot block canonical fact access or normal play.

Campaign export/restore must preserve or reconstruct these projections using the
owning Narrator/pilot contracts. Campaign switches and restored timelines fence
old jobs and discarded-future recall before further output can publish.

## 9. Proposed place in the v2 program and TITAN phases

Recommendation: a companion builder track with explicit TITAN integration gates,
not a wholesale expansion of the engine's P4 or a prerequisite for every Titan
capability. Build-time enrichment can deliver value before live TITAN exists;
existing modules must remain usable without the new metadata.

The following is a proposed integration map. It does not renumber or mark complete
any existing phase, change its immutable criteria or revise the program timeline.

| Builder phase | Deliverable and exit evidence | Dependency/integration |
| --- | --- | --- |
| MB0 - Audit and contract prototype | Audit current ingest/uploader/continuity; manually model a small real module slice, its source changes and dependencies; owner reviews direction | Can begin as planning/read-only work; agree ownership with TITAN P0 and pilot contracts |
| MB1 - Faithful source model | Source-grounded normalized packet, uncertainty/provenance and reviewed adaptation diff; missing/ambiguous extraction fixtures pass | Reuse reviewed uploader lane; no TITAN worker dependency |
| MB2 - Seed-enriched playable blueprint | Bounded seed selection, complete standalone adventure and matching NEQ representation; human-DM review and consistency checks pass | Accepted pilot retrieval/provenance contract; fixtures allowed during development, approved seed required for release claims |
| MB3 - Campaign binding and continuity | Validated entry variants, identity reconciliation, explicit relationship commits, standalone fallback and isolated replay | Narrator event/fencing foundations and pilot evidence/instantiation substrate; align with TITAN P1 |
| MB4 - TITAN adaptation consumer | Blueprint permissions/dependencies mapped to exact typed operations; rejected invalid changes, lazy actor enrichment and legal intervention examples | TITAN P0 policy, P3 scheduling, P4 publication and P5 personification as applicable |
| MB5 - Cross-module experience and portability | Divergent campaign histories, consequences across module boundaries, legacy fallback and restore/export evidence | TITAN P6 integration; Narrator/pilot portability contracts |

TITAN P2 owns alignment evaluation. The builder may provide value tensions and
tentative affinity cues, never pre-awarded success, compulsory Titan roles or
separate Good/Evil versions of the adventure.

### Proposed follow-up changes to owning plans, after review

1. Add the builder as a companion track in the program index, including shared
   contract ownership and dependency edges rather than speculative calendar dates.
2. Extend TITAN P0 with the reviewed blueprint-consumer boundary; P4 with operation
   mappings and dependency protection; P5 with lightweight actor foundations; P6
   with integrated cross-module scenarios. Preserve existing gates and non-goals.
3. Reconcile uploader/import planning and continuity versioning explicitly, retaining
   a single reviewed intake path rather than parallel new ingestion workflows.
4. Allocate module-note/Historian responsibility only after reviewing existing
   Narrator and memory contracts. Do not block early builder phases on a new agent.

Those files are not changed by this draft. Implementation should use focused,
approved OpenSpec changes; the existing engine remains independently scoped.

## 10. Review prototype and acceptance strategy

Start with a small real module slice: one antagonist, one faction pressure,
connected locations and an important information/access dependency. Include an
outgoing relationship that can affect a second module. Keep source and seed rights
clear and preserve the unmodified baseline for comparison.

Required evidence for the proposed track:

| Gate | What must be demonstrated |
| --- | --- |
| Source fidelity and adaptation | Extracted meaning is traceable; omissions are explicit; significant changes are justified rather than attributed to the source |
| Enrichment quality | Selected fragments create coherent, distinctive playable relationships; incompatible/redundant suggestions are rejected |
| Standalone playability | A human DM can understand and run the slice from its readable material without NEQ, TITAN or hidden seed lookup |
| Representation agreement | Human and machine presentations agree on important facts, mechanics, identities and dependencies |
| Consequential divergence | At least three continuations from the same reviewed baseline, including rejected/defeated Titan intent, remain coherent without forced convergence |
| World continuity | A committed cross-module connection constrains a rival Titan and later module entry; new notes cannot fabricate or override it |
| Knowledge and commitments | Private plans do not leak through actors; an unseen committed garrison cannot be freely replaced; reports remain attributed |
| Compatibility and failure | Legacy module without hints, TITAN disabled, provider/seed outage and stale work have explicit safe behavior; no incomplete build is silently published |
| Isolation and portability | Campaigns using the same module develop different histories without asset mutation or cross-campaign leakage; restart/restore discards stale-future projections |

Automated checks must cover schema/reference integrity, source and seed provenance,
continuity strict/warn-first behavior, identity conflicts, operation preconditions,
dedupe and recovery. Shared runtime paths require one-PC and multi-PC coverage.
Human review assesses adventure quality and standalone usability; fluent prose or
schema validity alone cannot establish either.

Runtime claims require the primary-orchestrator-owned isolated capture process
specified by repository guidance and the owning TITAN acceptance criteria. A
printed/readable artifact or a successful builder run does not establish live
TITAN success. Preserve input/output versions, expected versus observed results,
review findings, state diffs and exact evidence paths. Ratify numeric budgets and
quality rubrics before implementation and acceptance collection.

## 11. Non-goals and unresolved review decisions

Not authorized here: runtime implementation, universal bulk import, topology
rewriting, cross-campaign shared event history, full actor dossiers at build time,
allied-NPC/PC control, new party-size gates, automatic encounter equalization,
unrestricted JSON mutation, autonomous module rewriting or a mandatory Historian.

Decisions for owner review:

1. Is this companion-track placement preferable to putting all builder work inside
   TITAN? Recommended: separate producer track with shared acceptance scenarios.
2. Which source adventure and second-module connection should anchor the prototype?
3. Which authored properties are protected by default, and which adaptations need
   explicit reviewer consent? Define this before automating enrichment.
4. What minimum human-DM presentation constitutes genuinely complete playability?
5. Should later campaign policy expose faithful/responsive/emergent adaptation
   profiles? Optional future design, not three independently authored formats.
6. Does cross-module note maintenance justify a Historian worker, or can an existing
   bounded projection mechanism supply it without another agent lifecycle?

The success test is not how much TITAN changes a module. It is whether a complete,
distinctive adventure becomes part of one remembered, causally coherent world whose
future remains open to the players.
