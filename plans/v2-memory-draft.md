# V2 Memory Architecture - Provisional Draft

Status: Provisional planning reference; not runtime implementation authorization.
Date: 2026-10-27

**The structured world-seed pilot has been delivered and awaits NEQ-TTRPG approval
and/or requested updates before NEQ-world exports the full seed.** This draft also
awaits further development of the V2 Narrator and TITAN game engine. Revisit it
after pilot review, full-seed delivery and as those plans and their approved
implementation contracts mature. This document describes shared memory needs and
open questions; it does not establish that the proposed gateway, Hindsight
integration or TITAN runtime already exists.

## 1. Purpose and authority

Preserve useful campaign continuity across characters, scenes, modules and sessions
without flooding prompts or confusing recollection with mechanical authority. The
intended experience is an attentive Narrator and world that remember consequential
choices while respecting player agency and character knowledge.

- [V2 Narrator](v2-narrator.md) owns its continuity, Hindsight, scoped gateway,
  compaction, agenda and campaign-portability planning. It is an independent track.
- [V2 TITAN Game Engine](v2-titan-game-engine.md) owns Titan identity, scheduling,
  personification, scoring and world-intervention requirements. TITAN consumes
  shared contracts; allied-NPC agents are an independent future workstream.
- [World seed handover](neq-world-handover.md) documents the delivered pilot,
  its contract, limitations and consumer-owned verification. Its current sections
  supersede the pre-pilot request retained in its historical appendix.
- [ADR-0016](../adrs/0016-two-plane-memory-architecture.md) establishes the
  historical store and bounded retrieval-plane split. Accepted ADRs, repository
  rules and active OpenSpec contracts take precedence over this provisional draft.
- The [February memory draft](archive/memory.md) is preserved for history. Its
  proposed SQL, weights, implementation order, test counts and performance claims
  are not current contracts. Historical links elsewhere may retain its former path.

This document does not authorize runtime work, create a delivery goal, or replace
the independent Narrator and TITAN plans with a parallel implementation track.

## 2. Design principles

1. **Canonical state stays canonical.** Python and existing state owners determine
   mechanics, persistence and committed outcomes. Memory and generated text cannot
   change HP, inventory, location, allegiance or other state by assertion.
2. **Separate history from the retrieval lens.** Preserve source material and
   evidence as practical; retrieve small, relevant, authorized context packs under
   explicit item, token, time and resource budgets. Historical completeness is a
   goal, not a claim that every stored entry is complete or verified.
3. **Stable identity, temporal roles.** A character's identity survives name and
   PC/NPC role changes, retirement and return; role changes do not erase knowledge.
4. **Append and correct.** Preserve original evidence where appropriate; record
   corrections, supersession and provenance instead of silently rewriting history.
   Retention and privacy policy remain subject to explicit future contracts.
5. **Scope before relevance.** Campaign, effective timeline, identity, permissions
   and knowledge boundaries are checked before ranking or generating a synthesis.
6. **Uncertainty is explicit.** Observations, summaries, reported claims and
   model inferences do not automatically become verified facts.

## 3. Baseline and re-audit

The following are code observations, not claims of complete TITAN readiness:

| Surface | Existing starting point | Remaining qualification |
| --- | --- | --- |
| `core/memory/memory_db.py` | SQLite migrations, entities, roles, journal entries, events, links, provenance and world-model tables. | Schema presence and row counts do not establish event quality, scope, complete provenance or a live Titan service. |
| `core/memory/memory_ingest.py` | Journal/history ingestion and backfill machinery. | Backfill is not equivalent to reliable capture of every committed outcome; assess source time, attribution, dedupe and uncertainty. |
| `core/memory/memory_retrieval.py` | Bounded milestone, entity timeline, scene-context and retirement/return APIs. | The scene API inspected does not take campaign, effective generation or caller perspective; existing ranking is not the future authorization contract. |
| `main.py` | Campaign milestone injection is attempted on the first validation attempt when party entity IDs are available. | This is a partial live integration, not general query-sensitive or perspective-aware recall; retry continuity needs review. |
| `core/memory/memory_portability.py`, `updates/save_game_manager.py` | Memory packages and save/restore lineage provide existing portability surfaces. | Full coordinated snapshots, immediate generation fencing and future worker/Hindsight portability require further work. |
| `core/memory/memory_db.py` seed bootstrap | Copies a seed into a runtime DB only if the runtime target does not already exist. | It does not merge a new seed into an existing campaign DB. |
| `core/memories/` and companion files | Existing file-backed companion continuity and per-PC relationship work. | Preserve current compatibility; audit divergence and plan a shared relationship contract before changing authority. |

The local `memory.db` inspected for this revision contains journal entries, memory
events, links and diary entries; its inspiration, world-model and provenance tables
were empty. These are local, dated observations, not population or quality guarantees
for another installation. Re-audit actual code, data and accepted contracts before
implementation. Do not treat raw row counts as evidence of verified campaign truth.

## 4. Evidence, knowledge and provenance

Keep these categories distinguishable throughout ingestion, storage, retrieval,
summarization and disclosure:

1. **Seed possibilities:** reusable source fragments not yet instantiated.
2. **Committed campaign facts and events:** outcomes accepted through the relevant
   Python-owned reconciliation or publication boundary.
3. **Attributed beliefs and reports:** testimony, rumours, mistakes, propaganda or
   lies; a report can be committed without its content being true.
4. **Conditional intentions:** plans, agendas, forecasts and hypotheses, not outcomes.

Raw transcripts, committed source events, local memory rows, Hindsight observations
and summaries have different provenance and are not interchangeable authorities.
One shared event, multiple summaries and repeated recall must not become multiple
independent evidence items. Preserve source and event IDs, transformations, confidence,
verification status, correction links and causal relationships as applicable.

The Narrator plan's proposed event envelope includes campaign/world identity,
worldline and effective generation, turn/commit identity, in-game and recording
times, stable participants, source evidence, correction status and perspective.
Import time must not silently replace occurrence time. Witnessing, learning and
disclosure are separate from participation: an event concerning someone does not
prove that person knows it. The actual storage ownership and schema are open.

Backfill should be previewable, resumable, bounded and idempotent; report ambiguous
time, identity and attribution rather than silently promoting inferred material to
verified fact. Never ingest coding-agent or developer Hindsight memory into gameplay.

## 5. Identity, scope and perspective

The required identity hierarchy distinguishes reusable authored world/module
versions, a campaign instance, save/worldline lineage, the effective generation
established immediately on restore/import/reset, and stable character/perspective
identities. Reuse existing identity and path abstractions; do not invent a competing
campaign registry or use a global database path as campaign identity.

The planned server-owned gateway resolves the caller and authorized campaign,
timeline, operation, perspective and visibility before retrieval or synthesis.
Unknown identity or missing scope fails closed. Model arguments or client-provided
bank names cannot grant access. TITAN's planned privileged access is limited to
authorized in-game perspectives within its campaign and timeline, through bounded
server-side fan-out; it does not transform another actor's belief into fact.

Narrator knowledge, character knowledge and player disclosure are distinct. Project
only witnessed, learned or otherwise justified knowledge into actor performance;
do not infer private player thoughts, intentions or permission to control PCs.
Character and Titan workers are not implied by reserving their future permissions.

## 6. Retrieval and relationship continuity

Reuse and evaluate existing canonical memory APIs rather than introducing a parallel
generic event database. Candidate retrieval should be bounded, stable and explainable,
with relevant source references and explicit uncertainty. Apply authorization first,
then evaluate scene, recency, identity, relationship and other ranking signals.
Item caps and token caps are separate; return no broad unscoped fallback for an
empty or unauthorized scope. Numeric weights, decay profiles and latency targets
need fixture-based ratification rather than inheritance from the historical draft.

Carry forward companion and relationship requirements independently of TITAN:

- Preserve per-PC relationships and distinguish shared/group-only evidence from
  evidence attributable to a particular character; support one-PC and multi-PC play.
- Distinguish witnessed events, inferred affect and current relationship state;
  avoid a permanent competing source of truth between file-backed and DB paths.
- Provide bounded operator diagnostics for absent, sparse, ambiguous and malformed
  evidence, and previewable targeted rebuild/recovery where contracts permit.
- Decide parser, bridge and relationship-state ownership based on a fresh audit;
  preserve legacy behavior until an approved migration replaces it safely.

TITAN can use shared identity, relationship and evidence contracts, but does not
own allied-NPC agents or acquire control of PCs and allies through memory access.

## 7. World seed integration - pilot under review

Treat seed material as versioned input, separate from campaign-specific history.
Use only material approved for the intended distribution; the pilot is not certified
for publication, legal clearance or blanket redistribution. A selected fragment is a possibility until it is
interpreted, instantiated under campaign identity, validated and committed. Record
stable seed IDs, source/version, transformations and resulting event/fact references;
disclosure may occur later. Never write campaign consequences back into shared seed
material or overwrite an existing populated campaign DB to install a seed.

### 7.1 Delivered pilot and review boundary

On 2026-10-27, read-only consumer inspection of `data/world_narrative_seed.db`
matched the handover SHA-256
`6dbefe49f72733d11cc1ae6c15c41f9ce97435235842192effd9295ab56bb66e`;
SQLite integrity was `ok` and the foreign-key check returned zero violations.
The file contained 41,216 atoms, 95 profiles, 41,216 statistics rows, 3,944
alignment profiles and zero atom relations. A basic JSON shape check found 240
v1-shaped envelopes and 229 legacy detail values that failed JSON parsing; this
was not complete v1 validation. The producer reports exactly 240 selected detail
cells changed; the other 40,976 atoms are not claimed as v1-enriched.

This supersedes the earlier empty-installed-seed observation, not the need for
consumer acceptance. NEQ-TTRPG must review the pilot and communicate approval
and/or requested changes to NEQ-world before the producer exports the full seed.
No approval, full export, consumer integration or runtime test is implied by this
draft. Review representative content, safety, provenance, alignment distribution,
schema and retrieval capability; reassess the final export independently. The
handover records unresolved reference-inventory findings outside the pilot scope
and limits its review of new prose; it is not certification of the whole corpus.
Pilot fixtures cannot replace the final production-seed release gate.

### 7.2 Provenance and retrieval contract

The structured detail envelope uses integer `schema_version: 1`, distinct from
the SQLite metadata version `1.0.0`. Keep `content_supported` annotations and
their exact evidence pointers separate from ordered `extensions` entries labelled
`inferred` or `authored`; preserve each entry's derivation and public references.
Evidence location/text correspondence is not itself proof of semantic entailment.
Neither annotation nor extension automatically creates a committed campaign fact.

Use stable exact public namespace/ID references, never label or textual-similarity
joins. Do not invent links because `atom_relations` is empty. Retrieval must be
deterministic and bounded; defensively validate version, duplicate keys, types,
finite numbers, enums, size/depth and other v1 contract limits. Missing, malformed,
unversioned, unsupported or invalid detail falls back to the base atom, rather
than discarding it or coercing the detail into v1. Basic seed retrieval must not
require Hindsight, embeddings, a provider or network access. Follow the handover's
current contract and independently verify any transient producer fixture copies.

Keep unknown, unaligned and known-neutral states distinct; never turn unknown
into a zero score. The seed's `ethical_score` runs Evil to Good and `moral_score`
runs Chaos to Order. Five-head affinity is a separate, confidence- and basis-labelled
concept, not moral alignment, actor control or independently evaluated Titan reward.
Unreliable information remains an attributed possibility, not established truth.

### 7.3 Schema and non-destructive consumer integration

The inspected existing `memory.db` `inspiration_atoms` table lacks the delivered
seed's `entity_kind` and `seed_detail_json` columns; it also has no
`alignment_profiles` table. The delivered seed lacks `source` columns described
by the superseded handover for alignment, conflict and deity bridge tables. Compare
actual DDL, code and migrations before deciding on an explicit adapter or additive
migration; do not invent source identities or silently modify the producer artifact.

The existing bootstrap copies a seed only when the runtime target is absent. Never
delete, overwrite or reset an existing campaign DB to install the pilot or full
seed. Define separate fresh-bootstrap and existing-runtime paths with versioned,
idempotent import or reference semantics, stable-ID conflict handling, backup and
tested rollback. Test against disposable fresh and existing-runtime copies; verify
campaign-row preservation, integrity, bounded retrieval, fallback and seed immutability.
Defer exact mapping, indexing and storage ownership until the pilot is reviewed and
the full export is verified; copying seed content into `memory.db` is not assumed.

## 8. Portability, recovery and resilience

Extend existing save/export ownership rather than adding a separate manual TITAN
workflow. A future consistent snapshot must account for canonical JSON, SQLite,
source evidence, seed versions, agendas, derived projections, worker/outbox progress
and scoped Hindsight export or reconstructable evidence. No single SQLite transaction
is assumed to cover JSON, SQLite and PostgreSQL.

Restore, import, reset and campaign switching must establish effective timeline
generation and fence old jobs immediately, before new publication. Scope caches,
retrieval and worker results to their original campaign and generation; discarded
futures and late A-campaign jobs must not contaminate current or B-campaign play.
Prove recovery after partial delivery and clean-server import without developer
paths, secrets or another campaign's global database dump.

Provider or memory outages may degrade gameplay to validated local anchors, current
state and bounded existing context. Correctness, authorization and publication fail
closed; do not fabricate recall, replay effects or silently broaden permissions.
Expose degraded state and offer bounded repair/replay where supported. The Narrator
plan's Hindsight production dependency is not waived by fallback behavior.

## 9. Optional controller considerations

Versioned policy, retrieval audits, shadow comparisons, bounded changes and rollback
may be useful for future human or automated control. EGO/RATIO and the World Observer
are not TITAN prerequisites; their independent uses are not deprecated by this draft.
Existing readiness tables and the surveillance DB do not establish a deployed
controller, a complete audit trail or a required integration. Any controller work
needs its own scope and approved contracts.

## 10. Open decisions and provisional acceptance questions

Before turning this reference into implementation requirements, reconcile with the
Narrator and TITAN P0 audits and active OpenSpec work:

1. Which existing campaign IDs, event/commit receipts, APIs and save boundaries are
   canonical? Which schema fields need migration, and which belong elsewhere?
2. How complete and attributable are existing journal-derived records? How will
   uncertain or duplicated legacy history be identified and corrected safely?
3. How are fact, report, belief, intention, actor knowledge and disclosure represented
   without turning summaries into new evidence or creating competing authorities?
4. What approval or updates should NEQ-TTRPG request for the pilot before full
   export? What final seed schema, license/provenance and versioned retrieval and
   existing-campaign migration contracts can be verified after delivery?
5. How will authorized campaign/generation/perspective scope be enforced across local
   retrieval, Hindsight fan-out, caches and prompt assembly, including denied requests?
6. How are relationship continuity, role transitions, companion recovery and actor
   knowledge projected without loss or cross-PC leakage?
7. How do committed evidence, provenance and dedupe feed TITAN's independently
   evaluated alignment ledger without giving plans or repeated recollections credit?
8. How are atomic publication, recoverable delivery, immediate restore fencing and
   clean-server campaign portability demonstrated across all participating stores?
9. What measured retrieval quality, latency, token/cost budgets and operational
   degradation thresholds are appropriate for real campaign fixtures?

Acceptance must include scoped and denied-access fixtures, ambiguous and corrected
evidence, seed-to-fact provenance, one-PC and multi-PC relationships, idempotency,
crash/retry recovery, campaign A/B isolation and restored-future fencing. TITAN's
live acceptance gates remain owned by its master plan; a green database unit test
or a populated seed alone is not an engine release verdict.
