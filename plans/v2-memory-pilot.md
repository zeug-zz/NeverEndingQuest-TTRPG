# V2 Memory and World Seed Pilot for TITAN

Status: Proposed planning and review reference; not implementation authorization.
Date: 2026-10-28

## 1. Executive decision

The delivered world-seed pilot can, in principle, be installed into a copy of the
existing campaign's `memory.db` without starting a new campaign. The current
bootstrap does not do that: it copies the seed only when the runtime database does
not exist. A separate, versioned, non-destructive import path and schema adaptation
are required. The pilot import is for testing and MUST NOT replace the proposed
fresh-campaign bootstrap path or overwrite an existing campaign database.

The current memory schema is a useful foundation, but is not yet sufficient for
TITAN's proposed campaign, timeline, provenance, perspective and world-continuity
requirements. The delivered seed's v1 detail envelope provides useful narrative
building blocks, but only a small pilot subset is enriched. Its suitability for
full-corpus export and TITAN use must be measured rather than assumed.

**Recommendation:** test on a consistent disposable copy of the existing campaign;
develop and compare the smallest viable memory and seed contracts; implement and
verify the selected substrate under focused OpenSpec changes; then independently
validate the full public seed. The result should be a documented, migrated,
reproducible `memory.db` and seed schema/database structure optimized against
TITAN-shaped evidence, not a claim that the TITAN engine itself is complete.

## 2. Authority and boundaries

- [V2 memory draft](v2-memory-draft.md) is the provisional shared-memory reference.
- [NEQ-world handover](neq-world-handover.md), current sections 1-10, owns the
  delivered pilot contract; its historical appendix is not the current schema.
- [TITAN master plan](v2-titan-game-engine.md) owns engine requirements and live
  engine acceptance. Its section 3 contains a dated, pre-delivery empty-seed
  observation and must be reconciled with the handover before implementation.
- [V2 Narrator](v2-narrator.md) independently owns Narrator continuity, scoped
  gateway, Hindsight, agendas and portability planning. Coordinate shared contracts
  rather than making its track dependent on this pilot.
- [ADR-0016](../adrs/0016-two-plane-memory-architecture.md), accepted ADRs,
  `AGENTS.md` and active OpenSpec contracts take precedence. The SQLite historical
  plane and bounded retrieval plane are distinct.

This document proposes a possible future `/goal`; it does not create, resume or
replace one, approve an OpenSpec change, authorize runtime implementation, or
authorize modifying the installed campaign. Goal creation and implementation require
explicit user direction. Work on a full NEQ-world export also requires producer
coordination and approval; this repository cannot assume control of that project.

Python and the existing canonical state owners remain authoritative for mechanics:
character files, party state and encounter files do not become projections of
`memory.db`. Memory stores evidence and narrative continuity; a memory assertion
cannot independently change HP, inventory, location, loyalty or other state.
No Titan agents, arbitrary state mutation, model training, allied-NPC control,
full engine release, or new party-size gates are included in this substrate pilot.

## 3. Current evidence and qualifications

Read-only local inspection on 2026-10-28, against the main database files using
SQLite immutable read mode, found the following. The observed WAL files were zero
bytes at that time; these are dated observations, not guarantees of a future snapshot
or of another installation. A live WAL database must be backed up with a consistent
SQLite-aware method, not by copying only its main file.

| Surface | Observation |
| --- | --- |
| Delivered `data/world_narrative_seed.db` | SHA-256 `6dbefe49f72733d11cc1ae6c15c41f9ce97435235842192effd9295ab56bb66e`, matching the handover; 41,216 atoms, 95 profiles, 41,216 statistics rows and 3,944 alignment profiles. |
| Pilot coverage | Handover reports 240 v1-enriched detail cells, not 41,216 enriched atoms. The other 40,976 are preserved legacy or otherwise unannotated material. |
| Existing `data/memory.db` | 18,486 memory events, 18,484 journal entries and 55,516 links in the inspected snapshot; inspiration atoms, profiles and statistics were empty. Counts do not establish completeness, truth or attribution. |
| Schema difference | Seed atoms include `entity_kind` and `seed_detail_json`; the inspected runtime atom table lacks both. The seed has `alignment_profiles`; the inspected runtime does not. |
| Integrity | `PRAGMA quick_check` returned `ok` for both snapshots; `foreign_key_check` returned no violations. This is not a full consumer validation or semantic test. |
| Bootstrap | `core/memory/memory_db.py:49-61` skips copying when the runtime path exists. It does not merge seed data. |
| Legacy provenance | The inspected `memory_event_provenance` table was empty. Existing journal-derived records must not be silently promoted to verified facts or automatically attributed to a campaign. |

The handover also reports 229 legacy detail values that fail ordinary JSON parsing,
364 unresolved public references and 13 ambiguous polymorphic references outside
the selected pilot scope, and zero `atom_relations`. The seed is not certified for
publication, legal clearance or blanket redistribution. Recheck all findings against
the exact final export; producer-reported fixtures and counts are not consumer test
results. The consumer did not run an import or gameplay test as part of this review.

## 4. Intended outcome and proposed future goal

### Candidate objective

Design, implement and verify a campaign-safe memory and public world-seed substrate
optimized for the proposed TITAN engine: preserve the existing campaign, import and
evaluate the delivered pilot without replacing fresh bootstrap, define and implement
the selected versioned memory and seed contracts, and validate them with realistic
continuity, provenance, isolation, retrieval and recovery scenarios. Deliver a
reproducible migrated test `memory.db`, seed contract and database structure, with
measured tradeoffs and a producer handover for the full public seed.

This objective is a draft for owner review, not an active goal. A future goal plan
must retain the entire objective and its completion criteria across all phases;
finishing one OpenSpec change or a green unit suite does not finish the goal.

### Proposed completion criteria

1. A reviewed architecture and concrete versioned schema, migration and ownership
   contracts cover the seed catalogue, campaign/timeline scope, evidence, knowledge,
   world continuity and TITAN integration seams in sections 6-7. Explicitly record
   which capabilities are implemented now and which remain future-engine contracts.
2. A consistent, restorable copy of the existing campaign accepts the pilot through
   a separately invoked idempotent import; repeat, conflict, crash and rollback
   tests demonstrate preservation. Fresh bootstrap remains a separate tested path.
3. A reproducible test database and hash-bound seed/fixture manifest can be built
   without relying on the developer's live campaign or transient producer paths.
   No private campaign data is published as a test fixture.
4. Bounded retrieval and scenario tests demonstrate the distinctions among seed,
   committed fact, attributed belief/report and conditional intention, plus exact
   provenance, denied access, campaign/worldline isolation and restore fencing.
5. The selected structures are justified against predeclared functional, quality,
   latency, token, size and recovery measures; documented benchmarks include both
   successful and failed alternatives and representative one-PC and multi-PC cases.
6. A producer-facing full-export contract documents versioning, stable IDs,
   reference resolution, coverage, derivation, validation and publication limits;
   actual full-seed delivery is independently verified against that contract.
7. Documentation, migrations, tests, recovery instructions and a TITAN-facing
   integration map are reviewed. Applicable validation and live evidence have
   recorded commands, expected/observed results and artifact paths.

Full-seed delivery and publication clearance depend on NEQ-world and the owner. If
the approved full export is unavailable or fails its gate, criterion 6 remains
blocked: a contract or pilot cannot be reported as full-export completion. A future
goal may close as unmet only with a concrete blocker and evidence, not by silently
dropping this criterion. Import into the actual installed campaign is a separate
owner decision after copy-based tests and a proven backup/restore procedure; the
goal's reproducible deliverable does not require mutating that campaign.

## 5. Existing-campaign pilot installation

The pilot import is a distinct, explicit operation; ordinary first-run bootstrap
continues to run only for an absent runtime target. Do not delete, reset, replace or
overwrite the installed `data/memory.db` to obtain seed content.

1. Identify the selected campaign and canonical paths; quiesce or fence all writers.
   Establish a SQLite-aware consistent snapshot, including committed WAL state, and
   verify that it can be restored. Preserve an untouched backup.
2. Work on a disposable copy. Inventory existing schema, migrations, source and
   target rows, and content conflicts before any mutation. Record canonical JSON and
   relevant campaign artifacts so unintended changes can be detected.
3. Apply explicit, additive, versioned consumer migrations or adapters. Preserve
   seed `entity_kind`, raw `seed_detail_json` and required approved public catalogues.
   Do not invent missing source identities or change the producer artifact.
4. Import seed reference data, not the seed's empty campaign/runtime tables. Use
   exact namespace and stable ID plus seed version; preserve content and provenance.
   Do not turn atoms into campaign events or facts.
5. Record a manifest: file hash, producer schema/content version, mapping/migration
   version, counts, conflicts, result and time. Identical re-import is a no-op.
   Changed content under an existing stable ID requires an explicit versioned
   conflict/upgrade decision; do not use blind `INSERT OR REPLACE`.
6. Use a transaction and tested rollback for the import; test migration failure,
   interruption and retry separately. Verify row preservation, integrity, FKs,
   seed immutability, bounded retrieval and restore on the copy.
7. Only after these tests may the owner separately authorize use against an installed
   campaign under a documented quiescence, backup, conflict and rollback procedure.

Future architecture may instead reference a versioned read-only seed rather than
copying its catalogue. Compare that option during the pilot, including portability,
seed-version retention and snapshot behavior. It does not change the requirement to
test the requested existing-campaign import on a copy.

## 6. Proposed memory database structure

These are logical responsibilities, not mandatory final table names. Audit and reuse
existing APIs and schema where appropriate; do not create a parallel generic event
store without a demonstrated need. OpenSpec design must provide actual DDL, keys,
constraints, versioning, ownership and migration/backfill rules before coding.

| Logical area | Proposed records and minimum semantics |
| --- | --- |
| Seed catalogue | Catalogue version, artifact hash, producer schema/content version, mapping version, public namespaces/IDs, original atom fields and detail, supported annotations, ordered extensions, reference catalogues, import receipts and conflict reports. Preserve versions referenced by campaign instantiations. |
| Scope and identity | Existing canonical campaign/worldline identity, effective generation, stable entities, aliases and temporal PC/NPC/ally roles. Reuse existing identity systems; do not treat a global DB path as identity. |
| Evidence and events | Source IDs, campaign/worldline/generation, event/commit identity, occurrence and recording times, participants, evidence provenance, confidence, verification, corrections and supersession. Import time is not occurrence time. |
| Facts and assertions | Committed world facts versus attributed reports/beliefs and hypotheses. A report can be committed while its content remains unverified. Explicit relationship and causal references do not become truth merely because they appear in a summary. |
| Seed instantiation | Seed version and exact fragment IDs, transformation/interpretation, campaign scope, validation, and resulting event/fact references. Instantiating a fragment does not rewrite the shared seed. |
| Knowledge and disclosure | Who witnessed, learned or was credibly told what, source and time; separately, delivery channel, recipients and disclosure state. Participation alone is not proof of knowledge. |
| World continuity | Versioned outlines, fronts, dependencies and clocks; distinguish present facts from conditional trajectories and plans. |
| TITAN integration seams | Conditional agendas and revisions; actor dossiers, assignment history and legitimate knowledge; session/draw state; typed proposals, validation, commit receipts and dedupe; forecast versus actual weather; information delivery. Store only the substrate or tested contracts necessary for the pilot, not autonomous engine behavior. |
| Independent evaluation seams | Versioned evidence classification, deduplicated outcome ledger and snapshots distinguishing alignment power, leverage and realized progress. Seed affinity and proposed effects are not rewards. Implement only what is required for representative substrate tests; the TITAN scoring workstream owns its rubric. |

Shared design invariants:

- Scope and authorization precede ranking; unknown scope or perspective fails
  closed. Titan privilege does not convert a belief to fact or leak it through an
  actor who could not know it.
- Repeated summaries, Hindsight recall and copied reports are not independent
  evidence. Existing journal-derived records require evidence-backed, previewable,
  idempotent backfill; ambiguity and unknown source time remain explicit.
- Restore/import/reset establishes effective generation before publication and
  fences stale jobs, caches and discarded futures. Coordination across SQLite,
  canonical JSON and Hindsight needs recovery and consistent snapshot contracts;
  a SQLite transaction alone cannot make those stores atomic.
- Keep identity, scope, version, status and provenance queryable and constrained;
  bounded validated JSON is appropriate for flexible detail, not as the sole home
  for isolation keys. Index measured bounded access paths, not speculative queries.
- Domain APIs own persistence; seed text and model output are data, not authority,
  executable instructions or permission for direct SQL or arbitrary state writes.
- Save concise plans, evidence and reasons, not private chain-of-thought. Preserve
  one-PC and multi-PC continuity and legacy behavior until an approved migration.

## 7. Seed assessment and producer request

### What is useful now

The v1 envelope supplies bounded context and typed actor, relationship, faction,
information, location and weather fragments. It separates `content_supported`
annotations and exact evidence pointers from ordered `inferred`/`authored`
extensions. It also distinguishes ethical and moral axes from five-head affinity.
These are appropriate ingredients for conditional world-building, not fixed
campaign history, a mandatory script, a mechanical rules source or a complete
NPC dossier.

Consumers must validate the full handover contract, including duplicate keys,
types, finite numbers, enums, limits, references and supported version. Invalid,
malformed, absent or legacy detail falls back to the base atom. Use exact public
namespace/ID references, never textual-similarity joins. Unknown, unaligned and
known-neutral remain distinct; symbolic affinity does not grant moral alignment,
control or Titan reward. Basic bounded retrieval must not require a provider,
network access, embeddings or Hindsight.

### Request before full public export

Ask NEQ-world to provide a reproducible, hash-bound, self-contained public export
and manifest with:

1. Producer schema and content versions; counts, coverage, exclusions, and stable
   ID policy including changed/deleted/merged IDs and public-safe migration maps.
2. Integrity and FK results plus explicit resolution checks for polymorphic public
   references. Report unresolved and ambiguous IDs; do not expose inaccessible
   private IDs or invent links. Define namespaces and exact target keys.
3. Coverage and validation distributions by atom type, entity kind, detail group,
   alignment state and affinity basis, including missing, invalid and legacy detail.
4. Definitions of weights, statistics and support counts, including whether support
   represents independent evidence; public-safe provenance, derivation and
   documented distribution/publication limitations and rights review.
5. Preservation of supported evidence separately from ordered inferred/authored
   extensions, with truthful derivation and no invented source-book identities.
6. Enrichment where approved material supports actor distinctiveness, relationships,
   fronts, information and disclosure, locations, weather and alternatives. Report
   gaps rather than fabricating content or mandating uniform coverage.
7. Real supported or explicitly authored relations, if available, with direction,
   meaning, confidence and derivation. Zero relations may be acceptable with an
   explicit composition fallback; similarity is not evidence of a relationship.

The pilot should test whether optional, versioned public compatibility, dependency
and consequence links materially improve composition. If justified, propose either
a new detail-envelope version or a separate relation catalogue, with mappings and
backward-compatible fallback. Do not demand an untested schema expansion or rewrite
the full corpus before the experiment identifies actual retrieval and quality gaps.

## 8. Phased OpenSpec outline

The names are candidate changes, not existing directories or authorization. P0
should audit active OpenSpec work and agree shared ownership with the Narrator and
TITAN plans before implementation. Each change needs explicit scope, non-goals,
dependencies, numeric budgets, failure/rollback behavior and verification.

| Phase / proposed change | Scope and deliverable | Exit evidence and dependency |
| --- | --- | --- |
| P0: `memory-seed-pilot-contracts` | Re-audit actual databases, identity, retrieval, save/restore and ongoing work. Fix stale planning references. Define representative fixtures, evaluation rubric, thresholds, ownership, privacy and producer questions. | Reviewed baseline, snapshot/restore protocol, conflict policy and measured acceptance matrix; no writes to installed campaign. |
| P1: `memory-seed-existing-campaign-import` | Add consumer schema adaptation, manifest, deterministic import, rollback and separate fresh-bootstrap verification. Build a reproducible disposable copy-based test. | Idempotent import, collision and interruption tests; campaign preservation and restore verified; seed unchanged. Depends on P0. |
| P2: `memory-seed-bounded-retrieval` | Validate v1 details and references, implement bounded seed retrieval and legacy fallback, preserve A/B provenance and alignment/affinity semantics. | Offline deterministic fixture suite including malformed and denied cases; documented caps and measurements. Depends on P0/P1. |
| P3: `memory-campaign-evidence-and-knowledge` | Compare candidate structures; implement selected scope, event/evidence, knowledge and seed-instantiation substrate or explicitly owned existing extensions. Design safe legacy backfill and corrections. | Scenario-based comparison, chosen DDL/migrations and evidence of isolation, uncertainty, dedupe and restoration. Depends on P0-P2 and coordination with Narrator ownership. |
| P4: `memory-titan-continuity-seams` | Exercise world fronts, actor continuity, conditional agendas, proposal/receipt and independent-ledger interfaces with bounded test fixtures; implement only substrate contracts needed for them. | Demonstrated TITAN-shaped use, no mechanical authority transfer, one-PC/multi-PC and cross-module continuity. Depends on P3; not a TITAN engine release. |
| P5: `memory-seed-portability-and-evaluation` | Reproducible clean-environment build, backup/restore, generation fencing, resource benchmarks, schema decision record and consumer documentation. | Repeated tests, measured quality/cost/latency, recovery and portability evidence; documented tradeoffs. Depends on P1-P4. |
| P6: `memory-full-public-seed-verification` | Agree producer contract and independently test delivered full public seed, content coverage, references, versioning and privacy/publication requirements. | Hash-bound full-export acceptance report or explicit blocker. Pilot and producer claims cannot substitute. May proceed alongside P3-P5 after P0, but final completion requires its gate. |

No phase implicitly authorizes the installed-campaign import or producer-side edits.
If an active Narrator or TITAN change already owns a shared capability, coordinate
and consume that contract instead of duplicating it. Phase order may be refined
with evidence, but completion criteria must not be weakened to hide a dependency.

## 9. Test and optimization regime

### 9.1 Baseline and preservation

- Freeze seed hash, schema, counts, validator version and self-contained snapshot;
  preserve or independently recreate the six handover fixtures with source hashes.
- Establish a restorable, SQLite-aware snapshot of the current campaign. Keep
  private campaign material in approved local test storage, never published fixtures.
- Record pre/post inventories and logical checksums for campaign rows and canonical
  state. Account explicitly for intended migration metadata changes.
- Validate every purported v1 pilot envelope against the full contract; shape counts
  alone do not establish conformance or semantic entailment.

### 9.2 Import, parsing and retrieval

- Exercise fresh and existing-runtime copies; identical retry, different content
  under the same ID, pre-existing rows, missing references, interrupted import,
  migration failure and rollback. Assert no partial installation is reported as
  success and no existing campaign history is lost.
- Exercise null, malformed, duplicate-key, unversioned, unsupported, invalid,
  oversized and excessive-depth details; retain the base atom on fallback.
- Verify deterministic bounded results, exact reference resolution, ordered A/B
  provenance, alignment signs and unknown/unaligned/neutral distinctions.
- Test authorization before ranking, unknown scope denial, actor knowledge limits,
  one-PC and mixed multi-PC relationships, and no broad unscoped fallback.

### 9.3 TITAN-shaped scenario suite

1. **Actor continuity:** build a limited dossier from authored constraints, known
   evidence and seed; preserve personality and legitimate knowledge across sessions.
2. **Faction front and counterplay:** a convoy dependency creates conditional
   opportunities; the party defeats or ignores a plan without forced convergence.
3. **News and knowledge:** an offscreen event leads to a delayed, partial or false
   report; record carrier, audience, belief and later correction separately.
4. **Weather:** distinguish a forecast from actual game-time conditions without
   inventing unsupported mechanics or rewriting history.
5. **Evidence and alignment:** one outcome may support multiple heads, but repeated
   recollections and uncommitted intentions earn no additional realized credit.
6. **Restore and isolation:** restore before an event; a discarded future and stale
   worker cannot influence the restored timeline or another campaign.
7. **Shared seed, divergent campaigns:** the same fragment yields different
   campaign-specific instantiations without contaminating either world.

For each scenario retain inputs, campaign/worldline identity, seed hash and IDs,
expected versus observed facts/knowledge, source and correction links, retrieval
results, actions/receipts, relevant state diffs, and failure or rejection reasons.
Use synthetic fixtures where private campaign data is not necessary.

### 9.4 Decision metrics and live boundaries

Before comparative tests, ratify concrete thresholds and scoring rubrics for
retrieval relevance, continuity, unsupported assertions, unauthorized disclosure,
provenance completeness, latency, token usage, storage size, import/recovery time
and operational complexity. Compare a minimal additive design with at least one
alternative justified by the P0 audit; include copied versus read-only referenced
seed if practical. Record unsuccessful options and resource costs, not only a
winning benchmark. Human review must judge narrative usefulness and causal
coherence in addition to automated correctness.

If an approved change requires live gameplay evidence, the primary orchestrator
must use the repository's isolated Capture_Arena process, not the installed
campaign or normal port. Preserve per-run inputs, state diffs, transcripts,
expected/observed checks and verdicts. Missing scenarios, leakage, timeouts or
degraded runs are FAIL or BLOCKED, not PASS. TITAN's full live acceptance remains
owned by its master plan; passing this substrate pilot does not complete the engine.

## 10. Review decisions requested

1. Approve or revise the future-goal objective and completion criteria, including
   the full public seed as a producer-dependent completion gate.
2. Confirm the existing-campaign pilot should first use a disposable consistent
   copy, with any installed-campaign import separately authorized after verification.
3. Agree whether the recommended logical schema responsibilities and exclusions
   provide the right foundation for the Narrator and TITAN tracks.
4. Approve the phased OpenSpec outline and the producer-facing requests, or identify
   changes before any goal or implementation is started.
