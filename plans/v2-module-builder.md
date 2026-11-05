# V2 Module Builder - Source-Grounded, TITAN-Ready Adventures

Status: Consolidated implementation plan for owner review; not runtime-build authorization.
Date: 2026-10-30
Scope: Faithful source ingestion, reviewed adaptation, seed-enriched playable
blueprints, human-DM presentation, campaign binding and TITAN integration.
Program index: [V2 narrative overview](v2-narrative-overview.md), Track E.
Planning predecessor: [Archived review draft](archive/v2-module-builder-draft.md),
retained as design history. This plan is the current builder planning baseline.

## 1. Purpose and intended experience

Build complete, distinctive adventures that a human DM can run without NEQ, TITAN
or access to the world-seed database. Produce the same adventure as compatible NEQ
artifacts with enough explicit identity, motivation, knowledge, causal structure
and adaptation permissions for TITAN to develop a campaign instance coherently.

The human-authored adventure supplies identity and initial dramatic shape. Selected
world fragments deepen relationships and playable choices. TITAN supplies competing
intent and responsiveness. Player decisions determine what actually happens.

The deliverable is neither a railroad nor an unfinished skeleton. A kidnapping is
an actor's conditional attempt, not guaranteed future history. The party can prevent
it, abandon the adventure, lose an important resource or defeat a Titan's plan.
The engine must accept those consequences rather than secretly force convergence.

This track completes the initial v2 planning set alongside Network, Narrator,
Memory Pilot and TITAN. It does not claim any of those implementations complete.

## 2. Authority, authorization and ownership

Repository rules, accepted ADRs and active OpenSpec contracts take precedence.
This plan authorizes documentation only. It does not create/resume a goal, create
an OpenSpec change or worktree, approve implementation, change operator flags or
modify an installed campaign. The owner reviews the whole planning set first;
implementation starts only after explicit approval on the reviewed clean B0 base.

| Owner | Responsibility and boundary |
| --- | --- |
| This builder plan | Faithful source model, reviewed adaptation, reusable blueprint, build-time enrichment selection, DM presentation, builder validation and campaign-binding inputs |
| `ModuleBuilder` and generation workers | Existing orchestration and content-generation ownership; prefer extension modules and compatible adapters |
| [Archived uploader](archive/module-uploader.md) and current OpenSpec contracts | Existing intake, artifact persistence, review/quarantine and rebuild foundations; archive status alone is not acceptance evidence |
| [Archived module import](archive/module-import.md) | Historical continuity baseline and deferred proposals for bulk inventory, canonical content-pool operations, progression ladders and scheduling; current code/OpenSpec own implemented contracts |
| [Memory pilot](v2-memory-pilot.md) | Seed catalogue/retrieval, producer validation, evidence/knowledge classes, seed instantiation and migration substrate |
| [Narrator](v2-narrator.md) | Committed event envelope, scoped gateway, Hindsight, effective-generation fencing, agendas, Archivist compaction and portability |
| [TITAN](v2-titan-game-engine.md) | Five heads, alignment evaluation, planning, lazy actor dossiers, typed intervention policy/publication, weather and engine live acceptance |
| [Network](v2-server-client-network.md) | Player projection, sync and invited-client delivery; builder review is an authorized host surface, not a player capability |

The builder is a producer, not a second runtime engine, seed importer, event store,
actor controller or mechanical authority. Python owns schemas, identities,
coordinates, topology, connectivity, persistence and publication. Shared runtime
paths retain one-PC and multi-PC behavior; no opportunistic party-size changes.

### 2.1 Reconcile existing plans explicitly

1. Preserve or explicitly version `continuity_contract`: `continuity_version`,
   `entry_state_variants`, `cross_module_refs` and `standalone_fallback`. New hints
   do not silently replace these fields or strict/warn-first behavior.
2. Interpret canonical-first import as a shared validated authored setting/content
    pool, not shared mutable events across campaigns. Reconcile the archived import
    plan's wording during MB0 before implementing binding. Optional profile overlays
   remain later bulk/world-mapping scope; campaign isolation is required now.
3. Retain one intake family. Markdown/PDF adapters, accurate-ingest evidence and
   adaptation must converge through reviewed contracts, not a rival uploader.
4. TITAN excludes topology rewriting. Dependency-aware adaptation cannot bypass
   map/movement authority or restore lost opportunities by inventing replacements.
5. TITAN P0 owns the superseding canon-apply ADR. Until accepted, this track cannot
   ship automatic campaign canon application. Build-output review and runtime
   canon-apply policy are separate approval boundaries.
6. Existing modules without blueprint metadata remain usable. Full runtime actor
   dossiers, assigned Titans and alignment rewards are not build prerequisites.

## 3. Audited starting point and unfinished build

The 2026-10-30 audit compared archived changes, current code and selected tests.
These are dated observations to recheck at B0, not permanent rollout facts.

| Layer | Existing implementation to reuse | Remaining gap |
| --- | --- | --- |
| Reviewed uploader | Markdown/PDF intake, normalization, persisted workspaces, review/quarantine, packet build, overwrite/rebuild protection | Not a universal editorial review of every adaptation or proof of complete extraction |
| Accurate ingest | Source manifests/graphs, multipass normalization, fidelity repair, source-locked blueprints, generator locks, entity preservation and final benchmark | Coverage checks do not prove all meaning, secrets, conditions or dependencies were preserved |
| Builder authoring | `ModuleBuilder`, worker context, structural repair, bounded editorial reconciliation and finishing | Existing handoffs do not express the full proposed blueprint |
| Adaptation | Versioned dossier, source profiles, retained/omitted/original elements, upload/text runtime routing, bounded revisions | Evidence is advisory; literal fidelity is `not_applicable`; no complete reviewed source-to-adaptation decision ledger |
| Publication | Staging, attempt/revision/source identity, semantic/mechanical gates, monster guardrails, registry/campaign checks and rollback | Must establish current end-to-end acceptance and reconcile known test drift |
| Presentation | Module-derived Homebrewery adventure writer, provenance/credits and Markdown hygiene gates | No demonstrated standalone human-DM completeness or semantic machine/prose agreement gate |
| World context | Read-only bounded provider, seed/context provenance and proposal ledgers | Production upload does not supply a provider; author input strips raw world context and forwards scalar provenance, not selected seed content |
| Continuity | Strict continuity finalization and cross-reference enrichment; campaign module-availability sync | Availability is not campaign instantiation, identity reconciliation or committed cross-module relationships |

### 3.1 Implementation anchors

- `core/generators/module_builder.py`: orchestration; workers own generation.
- `web/routes/toolkit_homebrew_routes.py`: upload and build/review lifecycle.
- `web/extensions/toolkit_adaptation_runtime.py`: shared runtime envelopes/handoffs.
- `web/extensions/toolkit_homebrew_packet_builder.py`: build and gate integration.
- `web/extensions/toolkit_text_adaptation_worker.py`: text-description route.
- `web/extensions/toolkit_module_finisher.py`: finishing and publication transaction.
- `utils/toolkit_source_manifest.py`, `toolkit_source_extraction.py`,
  `toolkit_homebrew_normalizer.py`, `toolkit_normalization_fidelity.py`,
  `toolkit_builder_blueprint.py`: source and legacy blueprint foundations.
- `utils/toolkit_adaptation_{dossier,source_context,builder_context,authoring}.py`
  and `schemas/toolkit_adaptation_dossier_schema.json`: adaptation handoff.
- `utils/toolkit_adaptation_{world_context,proposals,provenance}.py`: world-context
  boundaries, not demonstrated build-time seed enrichment.
- `utils/toolkit_adaptation_{gate_composer,publication_convergence,revision}.py`
  and publication/registry/campaign helpers: validation and recovery foundations.
- `utils/homebrewery_adventure_writer.py` and
  `utils/toolkit_adaptation_markdown_quality.py`: presentation and hygiene.
- `utils/toolkit_narrative_enrichment_plan.py`: artifact-only placeholder, not an
  implemented seed-enrichment engine; do not revive its stance/playline profiles.

Audit exact APIs and schemas before choosing new names or relocating ownership.

### 3.2 Evidence qualifications

- Current `model_config.py` enables adaptation and canonical monster generation;
  configuration helpers still fail safely to disabled on missing/invalid values.
  Inventory real operator policy rather than calling the deployed route default-off.
- Historical runtime-unification acceptance includes a live `ready_dossier`
  authoring result, not complete staging/publication. Later production-convergence
  acceptance includes one provider call returning `provider_response_malformed`:
  evidence of safe failure, not successful live convergence or publication.
- Some archived tasks remain unchecked. Later Numillian work superseded parts of
  earlier blocker history: the inspected current stored report says ready,
  publishable and source fidelity pass, overall degraded. It was not freshly
  validated in this audit. Do not reintroduce historical blockers as current facts.
- Focused current tests passed 63 source/world/dossier/Markdown tests, 134 route/
  context/convergence/gate/campaign/registry tests and 52 adventure-writer tests.
  The separate 23-test text-description failure-guard suite has five failures:
  build-identity validation rejects raw-success fixtures before expected finisher
  assertions. Reconcile fixture versus runtime contracts; do not weaken identity
  validation merely to turn tests green. Broad adaptation discovery timed out at
  120 seconds and establishes no current all-green result.

MB0 must reproduce/classify this baseline and retain exact commands, logs and
protected-state hashes. No new feature may quietly inherit an unexplained failure.

## 4. Target pipeline and publication boundaries

```text
Permitted human source + maps/media + rights declaration
  -> immutable source workspace and extraction evidence
  -> source-grounded normalized model + uncertainty/omission ledger
  -> proposed adaptation changes + reviewer decisions
  -> bounded compatible seed suggestions + acceptance/rejection provenance
  -> reviewed reusable adventure blueprint/version
       -> complete human-DM presentation and permitted player material
       -> compatible NEQ artifacts and TITAN-facing structure
  -> representation agreement + existing strict publication gates
  -> reusable module publication

Selected module version + authorized campaign snapshot
  -> entry/identity reconciliation and proposed bindings
  -> Python validation + required approval + canonical commit receipts
  -> campaign effective state, scoped continuity projections and TITAN inputs
  -> legal interventions and player consequences, never reusable-asset mutation
```

Extraction fidelity, adaptation acceptability, module readiness, publication and
campaign binding MUST remain separately reported. A passing stage cannot stand in
for another. A seed-enriched release cannot silently become an unreported seedless
fallback. A rejected enrichment or uncommitted proposal is not a module/campaign fact.

## 5. Logical representation and migration contracts

These are required meanings, not preselected filenames, SQL tables or a parallel
canonical state model. MB0 chooses compatible schema extensions/adapters and MB1/2
implement them through current owners.

### 5.1 Source model and adaptation decisions

- Preserve input hashes, source format/version, page/section/block references,
  source rights, maps/media references and extraction/tool versions.
- Capture premise, distinctive tone, actors, factions, locations, encounters,
  secrets, clues, rewards, rules, conditions, storyline and possible outcomes.
- Separate explicit source statements from uncertain interpretation, conflicting
  evidence and missing extraction. Never repair a source gap with invented source.
- Give material elements stable source references. Every significant retention,
  omission, rewrite, mechanical conversion or generated addition needs a reason,
  affected references and reviewer decision; harmless formatting is not editorial
  consent. Invalidate affected approvals when source or decisions change.
- Support chunked/section-aware coverage. Current context bounds must not silently
  truncate the only evidence for an actor, clue or ending. Persist coverage and
  explicit partial/blocked outcomes when a source cannot be handled within budget.
- Source-less text-description builds remain supported: label their user brief and
  generated additions truthfully rather than inventing external source evidence.

### 5.2 Reusable blueprint

| Area | Minimum semantics |
| --- | --- |
| Identity | Premise, tone, tensions, protected authored truths, supported level range, source/adaptation rationale |
| Initial situation | Stable actor/location/faction identities, resources, relationships, starting conditions and campaign commitment boundaries |
| Trajectories | Human-DM overview; conditional attempts, triggers, likely developments, alternatives, refusal/failure/abandonment consequences |
| Dependencies | What clues, keys, actors, information routes and resources enable; preconditions, affected opportunities and justified alternatives |
| Actor foundations | Roles, motives, relationships, legitimate starting knowledge, resources/capabilities, constraints and optional seed/affinity cues |
| Encounters | Placement, supported SRD 5.2.1 mechanics, hazards, quantities, rewards, retreat/negotiation/noncombat options where appropriate |
| Information | Secrets, attributed rumours/beliefs, witnesses, discovery routes and disclosure permissions |
| Adaptation permissions | Protected content, allowed variations, typed hooks, preconditions, risk and validators; no arbitrary JSON mutation |
| World connections | Incoming/outgoing relationship candidates, continuing actors, entry variants and standalone fallback |
| Provenance | Source references, seed version/IDs, transformations, generated additions, uncertainties, approvals and build versions |

A key marked merely essential is insufficient. Record the opportunity it enables
and the consequence of losing it. Do not resurrect the key-holder or materialize an
unearned replacement to preserve completion. No exhaustive branch tree or five
head-specific adventure variants are required.

### 5.3 Truth and commitment classes

| Class | Required treatment |
| --- | --- |
| Protected authored history | Preserved in the reusable model; binding conflicts require explicit reconciliation |
| Initial situation | Becomes campaign fact at its declared instantiation boundary, not whenever convenient |
| Conditional future | Agenda/trigger; not an event that has happened |
| Permitted variation | Chosen within declared limits before dependent commitment |
| Report/belief | Attributed source and acquisition; committing the report does not verify its contents |
| Unresolved possibility | No prior existence or causal effect until valid instantiation |

An unseen committed garrison is not freely replaceable. Actor knowledge is not
Narrator/Titan knowledge. Similar names or motifs are not identity evidence.

### 5.4 Versioning, reproducibility and legacy compatibility

Persist source/seed hashes and versions, model/task/profile identifiers, build and
schema versions, selected fragments, approved outputs and reviewer decisions.
Stochastic rebuilds need not be byte-identical; accepted versions must remain
inspectable and reproducible as retained outputs with traceable inputs.

Define adapters for legacy packets, dossiers and modules, including absent metadata,
unsupported versions and malformed fields. Missing new hints must not break ordinary
legacy play. A malformed claimed v2 contract cannot silently fall back as valid v2.
Upgrading authored assets must not retroactively alter an existing campaign binding.
Provide explicit preview/conflict handling, pinning and rollback for upgrades.

## 6. Enrichment, presentation and campaign continuity

### 6.1 Build-time seed enrichment

Consume the pilot's catalogue/retrieval API, not a new importer or direct extension
SQL. Retrieve a bounded relevant selection by source needs and blueprint context.
Validate supported detail, exact public IDs, rights and reference resolution before
use. Zero producer relations is acceptable only with honest authored-composition
provenance, not invented seed relationships.

Pass actual selected, permitted fragment content into generation through an
explicit data boundary, separate from scalar report provenance and private campaign
state. Record each accepted/rejected suggestion, compatibility reasoning, affected
entities, seed version/IDs and transformation. Measure specificity, causal coherence
and playable choices, not fragment count or lore length.

Build-time accepted content becomes part of the reusable authored baseline; campaign
instantiation controls its commitment. Runtime retrieval remains TITAN-owned and
cannot overwrite established personality/history. Curated fixtures support
development but cannot satisfy production seed verification or rights clearance.

### 6.2 Two presentations of one reviewed model

The human-DM and NEQ/TITAN presentations MUST be projections of one approved model.
The readable version needs background, usable keyed places/actors, encounters,
mechanics, maps/references, clue meaning, rewards and guidance for unexpected choices,
refusal and failure. No hidden runtime lookup may be required to run the adventure.
Readable print-oriented source is in scope; PDF/rendering technology is a later
design choice, not a reason to defer complete running instructions.

Compare identities, quantities, placement, mechanics, knowledge, dependencies and
conditions across outputs. Markdown hygiene remains necessary but insufficient.
Separate DM secrets from player handouts. Preserve attribution and public/private
artifact boundaries: local conversion permission is not redistribution permission.

### 6.3 Campaign binding and derived continuity notes

Bind an exact module version to campaign/worldline/effective generation using
Narrator identity/fencing and pilot instantiation/evidence APIs. Validate entry
conditions, reconcile exact identities, propose relevant relationships and commit
accepted bindings through canonical APIs with receipts and retry dedupe.

Continuity notes are campaign-scoped derived projections: relevant committed changes,
relationships, obligations, incoming consequences and separately attributed beliefs
and future pressures. Carry source event IDs, coverage/high-water mark, revision,
scope and visibility. Never append played history to authored backups or treat
repeated notes as new evidence. Canonical fact access remains available if notes lag.

MB0 assigns ownership for a bounded projection function; MB3 implements it using
existing event/memory infrastructure where possible. A mandatory new Historian agent
is not justified. The Narrator Archivist continues to own context compaction, not
arbitrary history invention, scoring or interventions. A separate worker requires
reviewed need, lifecycle and ownership, not a new source of truth.

## 7. Phased OpenSpec implementation outlines

Names below are proposed focused changes, not existing directories, approved scopes
or commands to execute now. Each later change must include proposal, design,
capability deltas and dependency-ordered tasks with exact current interfaces,
numeric budgets, non-goals, migration/rollback, automated tests and evidence gates.
Do not reopen archived tasks to disguise new scope; reference their provenance.

### MB0 - Clean-base audit, baseline closure and contract prototype

Proposed changes: `module-builder-v2-baseline-closure`, then
`module-builder-v2-contracts`.

Dependencies: owner planning review and verified B0 for implementation. Read-only
planning/prototype design can precede B0. Coordinate Pilot P0 and TITAN P0 contracts;
do not wait for TITAN runtime to define builder-only source requirements.

Tasks:
1. Record B0 SHA, active/archive scope, real flags, input routes, artifact versions,
   canonical APIs and protected-state inventory. Reproduce current focused failures
   and broad discovery behavior with finite, isolated test runs.
2. Resolve the five text-description identity/finisher failures according to current
   authority contracts. Repair tests if fixtures are stale; repair runtime if actual
   behavior is wrong. Classify timeout/test-isolation debt rather than masking it.
3. Inventory review, coverage, rights, Markdown/media, continuity and publication
   gaps. Run a bounded authorized build through real author, builder, gates and
   finisher against disposable state; provider contact alone is not success.
4. Select a rights-clear real slice: antagonist, faction pressure, connected places,
   important information/access dependency and outgoing second-module relationship.
   Preserve the unmodified source. Reuse TITAN's Malarok exemplar if suitable rather
   than requiring a rival flagship; record the selected fixture and reason.
5. Manually model source evidence, proposed changes, truth classes, dependency loss,
   standalone fallback and the two presentations. Review before schema commitment.
6. Agree protected properties/consent, continuity versioning, projection ownership,
   seed adapter boundary, source/media support and minimum human-DM completeness.
   Reconcile import-plan links and canonical-content versus campaign-history wording.
7. Ratify measurable quality/running-cost budgets and a cross-track acceptance map.

Exit: reviewed baseline/prototype, explained regression state, working bounded
end-to-end evidence or an explicit blocker, and approved contracts. No clean-base
claim without recorded revision/status and no successful-publication claim from a
mocked finisher. Later release acceptance requires the real success path.

Rollback: retain current production routing; prototype/repairs use isolated copies.
No operator flag change or installed-campaign remediation is implicit.

### MB1 - Faithful source model and reviewed adaptation

Proposed changes: `module-source-model-v2` and
`module-adaptation-review-ledger`.

Dependencies: MB0; existing uploader contracts. No TITAN worker, Hindsight service
or production seed is required for source-only correctness.

Tasks:
1. Version/extend normalized source evidence with stable references, coverage,
   uncertainty and omissions; preserve Markdown/PDF adapter identity and map/media
   provenance. Reject unsupported/ambiguous extraction explicitly.
2. Reuse multipass/fidelity tooling with section-aware completeness checks for
   secrets, conditions, rewards, actors and later source sections, not only counts.
3. Persist source interpretation separately from adaptation. Implement meaningful
   retained/changed/omitted/generated decisions and reviewer approval/invalidation.
4. Integrate preview/review/retry into the existing host toolkit and artifact
   workspace, including text-description builds and rights-restricted failure paths.
5. Retain source and approved decisions across retry/resume; pin attempt/source
   identity and prevent silent downgrade between routes.

Exit: real-source fixture and missing/ambiguous/oversized/conflicting-source tests
demonstrate traceability, explicit incompleteness, review rejection and stale-approval
invalidation. Invented additions cannot pass as extracted facts.

Rollback: compatible readers/legacy route remain; incomplete new work stays staged.
Do not reinterpret existing published modules as approved v2 models by inference.

### MB2 - Seed-enriched complete playable blueprint

Proposed changes, split by ownership:
- `module-playable-blueprint-v2`: structure, dependencies and worker handoff.
- `module-seed-enrichment`: pilot retrieval consumer and review/provenance.
- `module-dual-presentation-gates`: readable adventure and agreement/publication.

Dependencies: MB1. Blueprint/presentation work can use labelled fixtures; real
enrichment integration consumes accepted Pilot P1/P2 APIs. Release claims require
Pilot P6's independently verified, permitted full seed, not merely pilot success.

Owner clarification (2026-11-05): MB2 uses the delivered 240-fragment pilot
to evaluate retrieval and blueprint composition and feeds schema gaps back to
the Memory Pilot/NEQ-world review. This evaluation does not wait for P6.
The optimized producer/consumer schema must be signed off before separately
authorizing the roughly 40k-fragment production job; only production-seed
release claims wait for P6.

Tasks:
1. Implement section 5 meanings through compatible existing schemas/adapters.
   Preserve Python topology and SRD mechanics; model conditional trajectories,
   dependency consequences, knowledge and lightweight actor foundations.
2. Pass approved content through `ModuleBuilder` into owning generation workers;
   preserve protected facts and declared variations across all generation/retry paths.
3. Connect actual bounded fragment retrieval/content, keeping safe data envelopes
   distinct from scalar telemetry. Reject incompatible/unlicensed/invalid candidates;
   retain rejected suggestions as review records, not facts.
4. Generate complete readable and NEQ projections from the approved model; validate
   semantic agreement and attribution, map/media references and secret boundaries.
5. Integrate with existing staging, mechanical/semantic gates, convergence, monster
   reuse/generation guardrails and recoverable publication. Separate source coverage,
   approved adaptation and enrichment status from legacy literal-fidelity metrics.
6. Run human-DM review without runtime access and compare enriched versus unmodified
   baseline. Demonstrate distinctive choices and causal relationships, not just prose.
   Extend the approved MB0 slice to at least one complete rights-clear exemplar
   module; slice quality cannot establish whole-adventure completeness. Exercise
   both uploaded-source and text-description paths through their shared contract.

Exit: a complete independently runnable exemplar adventure, matching machine
artifacts, reviewed enrichment with exact provenance, rejected incompatible
suggestions, and real staged
publication success. Provider/seed failure, budget exhaustion and malformed outputs
retain inspectable work without false completion. Production-seed dependency remains
BLOCKED if unavailable; fixture development does not waive it.

Rollback: pin approved prior module versions and review state; disable enhancement
through explicit policy without silently relabelling a seedless build as enriched.

### MB3 - Campaign binding and cross-module continuity projections

Proposed changes: `module-campaign-binding-v2` and, if separately useful,
`module-continuity-projections`.

Dependencies: MB2's reviewed producer contract; Narrator P1/P2 event identity,
portability and fencing; Pilot P3 evidence/instantiation substrate. Coordinate Pilot
P4/TITAN P1 continuity seams. If conditional records are published as agendas, consume
Narrator P5 rather than creating a private agenda implementation.

Tasks:
1. Bind a pinned reusable version; extend continuity entry variants, cross-module
   references and standalone fallback with strict/warn-first compatibility.
2. Reconcile actor/place identities and history before dependent play. Preview
   conflicts; record accepted variation and the precise commitment boundary.
3. Commit authorized relationship/binding events through owning APIs, with expected
   revisions, dedupe, correction links and recovery across JSON/memory boundaries.
4. Build bounded evidence-linked continuity notes after relevant commits; support
   recomputation, corrections, high-water marks and visibility. Keep them off the
   player-turn critical path; no invented bridging history when evidence is absent.
5. Add binding/projection state to the owning save manifest and fence stale jobs on
   switch/restore. Test two campaigns sharing immutable authored assets.

Exit: validated independent bindings, concrete committed cross-module relationships,
correct entry/fallback after refusal or dependency loss, idempotent retry/correction,
and restore/isolation evidence for one-PC and multi-PC parties. Module availability
alone cannot satisfy this gate.

Rollback: reject/unbind only uncommitted work; preserve committed history and use
explicit subsequent/corrective events. Restored timelines fence abandoned futures.

### MB4 - TITAN blueprint consumer and dependency-safe adaptation

Proposed change: `titan-module-blueprint-consumer`, coordinated with the owning
`titan-intervention-publication` and `titan-actor-personification` changes.

Dependencies: MB3; TITAN P0 accepted policy/operation contracts, P3 scheduling and
P4 publication. Personification scenarios additionally require TITAN P5. Draft
consumer contracts may be fixture-tested earlier; live claims wait for their owners.

Tasks:
1. Map blueprint hooks to exact typed TITAN operations, canonical owners, risk,
   validators, resources/declarations and visibility. Metadata is not write permission.
2. Validate dependencies and committed facts at proposal and publication time;
   reject stale work, protected-content violations and unsupported mechanics.
3. Supply lightweight actor foundations to lazy dossiers with legitimate knowledge;
   preserve actor continuity and PC/allied autonomy. Affinity is not assignment or
   realized alignment reward; TITAN P2 remains the evaluator.
4. Exercise accepted low-risk changes and rejected high-risk/illegal changes under
   the approved policy. No topology rewrite, retroactive garrison deletion, dead-actor
   duplication or magical replacement of a lost dependency.
5. Verify TITAN-disabled and legacy-module behavior without mandatory metadata.

Exit: operation-by-operation mapping, legal intervention and rejection receipts,
defeated/rejected Titan intent, and knowledge-safe actor behavior in orchestrator
captures. Builder success does not establish TITAN success.

Rollback: stop pending enhancements while preserving committed effects, ordinary
gameplay and pinned assets. No rollback may erase inconvenient player consequences.

### MB5 - Integrated cross-module experience, portability and release

Proposed change: `module-builder-v2-live-acceptance`.

Dependencies: MB0-MB4, relevant TITAN P6 integration, Narrator portability and pilot
P5/P6. Coordinate shared captures instead of duplicating tests or claiming another
track's release on the strength of this one.

Tasks:
1. Demonstrate at least three coherent continuations from the same approved baseline,
   including refusal/abandonment and defeated Titan intent, without forced convergence.
2. Commit a connection into a second module; show it constrains a rival head, later
   module entry and returning actors. Separate fact, rumour, intent and disclosure.
3. Demonstrate divergent histories from shared assets, save/restart, campaign switch,
   restore-before-event and clean-server export/import. Reject discarded-future jobs.
4. Repeat required legacy/TITAN-off/provider/seed-outage and publication-recovery cases.
   Check protected assets and public/private exports, review budgets and quality.
5. Record host operating/recovery instructions, version upgrade policy, final release
   manifest and all mandatory gate verdicts. Enable only reviewed surfaces.

Exit: every section 9 gate passes with preserved evidence and owner-reviewed quality;
no missing production seed, human review, live scenario or portability result is
waived. A blocked integration dependency leaves the full track incomplete.

## 8. Program sequencing and worktree implementation

The overview owns scheduling, not requirements. The intended partial order is:

```text
Owner reviews complete initial planning set -> B0 clean/reviewed base
  -> MB0 -> MB1 -> MB2 blueprint/presentation (fixture development allowed)
Pilot P1/P2 -----------------> MB2 actual seed retrieval
Pilot P6 --------------------> production-seed release clearance
Narrator P1/P2 + Pilot P3 ---> MB3 binding/projections
Narrator P5 -----------------> published conditional agendas, if used
MB3 + TITAN P0/P3/P4 --------> MB4 operations; TITAN P5 -> actor scenarios
MB4 + TITAN P6 + portability -> MB5 integrated acceptance
```

Network, Narrator and early TITAN work do not wait for this entire track. TITAN can
develop against legacy modules and contract fixtures; only builder-specific consumer
and joint acceptance scenarios require the new blueprint. Seed enrichment delivers
value before live TITAN exists. Bulk inventory/progression/scheduling remains a later
import track, not an early builder prerequisite or a hidden requirement for MB5.

Proposed worktree B: `feature/v2-module-builder`, created only after owner approval
and B0. Do not move the dirty planning checkout or any active goal into it. Record
the actual base SHA, dedicated venv/config provision, isolated staging/ports and
reviewed per-phase OpenSpec scope before implementation.

Merge small phase PRs through `origin`; rebase dependent tracks after shared
contracts land. Serialize `memory.db` migrations through the owning Narrator/pilot
chain. Coordinate toolkit host changes with Network's `web/` work; do not include
builder review controls in the player client. Shared live captures serialize on
port 8360; never use the installed campaign or ordinary port 8357.

### Candidate later goal objective

Deliver the reviewed v2 module-builder track end to end: source-grounded reviewed
adaptation, reproducible permitted seed enrichment, complete and agreeing human-DM
and NEQ blueprints, campaign-safe binding/continuity, dependency-safe TITAN consumption
and verified cross-module portability, preserving legacy modules and Python authority.

Create a goal only when explicitly requested. A later goal retains all phases and
completion criteria; a blocked seed/TITAN dependency is not permission to close after
MB2. Independent phase work may be reviewed and merged without claiming full delivery.

## 9. Acceptance, measurements and evidence

| Gate | Phase | Required evidence |
| --- | --- | --- |
| B1 Baseline and routing | MB0 | Current failure classification, identity-safe input/finisher behavior and actual staged end-to-end success |
| B2 Source meaning and review | MB1 | Traceable meaning/coverage, explicit ambiguity/omissions, approved changes, rejected/stale approvals and no invented source |
| B3 Enrichment quality | MB2 | Actual selected content, exact seed references/rights, accepted/rejected suggestions and human-reviewed causal/playable value |
| B4 Standalone presentation | MB2 | Human DM reviews/runs the prototype and complete exemplar without server/seed access; complete running information, not a raw data dump |
| B5 Representation agreement | MB2 | Matching identities, quantities, locations, mechanics, dependencies, knowledge and secret boundaries |
| B6 Binding and continuity | MB3 | Strict/warn-first compatibility, identity conflicts, receipts, corrections, fallback and evidence-linked notes |
| B7 TITAN legality/knowledge | MB4 | Typed operations, defeated/rejected intent, preserved dependencies and no privileged knowledge leakage |
| B8 Consequential divergence | MB5 | Three coherent continuations, rival-head constraints and subsequent second-module consequences |
| B9 Compatibility/resilience | MB1-MB5 | Legacy module, TITAN off, missing/invalid seed, provider failure, stale work and recoverable interrupted publication |
| B10 Isolation/portability | MB3/MB5 | Independent campaigns, unchanged authored assets, generation fencing, restart/restore and clean-server export/import |

Before implementation MB0 must ratify numeric thresholds for source/fragment counts,
chunk/context/output size, retrieval/tool/provider calls, revisions/retries, elapsed
time, tokens/cost, concurrency, staging size, background lag and recovery. Start from
existing bounded behavior; widening budgets requires evidence and review. Cost or
deadline exhaustion preserves artifacts and reports a partial/blocked outcome, never
an unbounded retry or falsely complete fallback. Human rubrics must cover source
identity, specificity, causal coherence, agency, playable completeness and usefulness.

Automated coverage includes malformed/versioned contracts, exact references, rights,
coverage truncation, identity/preconditions, dedupe, crash/retry, stale source/review,
continuity strict/warn-first, disclosure, asset immutability and legacy fallback.
Shared runtime changes require the one-PC regression floor and multi-PC behavior,
with four PCs the primary scenario shape. Fluent prose and schema validity are not
substitutes for human review or live evidence.

Run focused tests with `.venv/bin/python`, applicable module/schema validators,
`python3 scripts/check_ascii_compliance.py --summary-only` for Python source changes,
and `git diff --check`. Later OpenSpec changes require strict change/spec validation.
Preserve exact commands/results; run report-writing module validation only on the
selected disposable copy, not the installed campaign by accident.

The primary orchestrator runs and judges required isolated runtime gates using
`.opencode/skills/neq-capture-arena/SKILL.md`, repository venv and port 8360.
Preserve per-run evidence under
`tmp/router-rollout/module-builder-v2/<gate>/<run-id>/`: source/module/seed versions
and hashes, party/campaign/worldline/generation, worktree/code revision, model/task,
review decisions, expected/observed assertions, transcripts, state diffs, receipts,
quality findings, budgets and artifact paths. Joint TITAN runs may reference one
immutable evidence set from both gate ledgers. Missing scenarios, leakage, timeouts
and unresolved contradictions are FAIL or BLOCKED, not a waived PASS.

### Full-track completion criteria

1. Source meaning is captured with explicit uncertainty and reviewed transformations.
2. Permitted production seed content is actually used with exact, inspectable
   provenance; its release dependency is independently verified.
3. A complete human-runnable adventure and matching NEQ blueprint pass human review
   and automated agreement/publication gates.
4. Campaign binding and continuity preserve identity, history, player agency and
   knowledge boundaries without rewriting reusable authored assets.
5. TITAN consumes permissions/dependencies through legal typed operations and accepts
   counterplay; builder metadata never grants mechanical or scoring authority.
6. Cross-module divergence, resilience, legacy behavior, isolation and portability
   pass all mandatory gates within reviewed budgets, with reproducible evidence.

## 10. Non-goals and owner review checklist

Excluded: universal bulk intake, OCR perfection, progression-ladder operations,
topology rewriting, cross-campaign event sharing, automatic encounter equalization,
full build-time actor dossiers, PC/allied-NPC control, arbitrary JSON/SQL mutation,
new party-size gates, five separately authored head variants, a mandatory Historian,
and an independently implemented seed/memory/runtime engine.

Owner review before worktree execution:
1. Approve the companion producer track and its B0/MB0-MB5 scope and completion criteria.
2. Select the real prototype and second-module relationship, confirming rights and
   whether the Malarok exemplar can be shared with TITAN.
3. Ratify protected properties, adaptation consent, standalone presentation quality
   and budget/rubric decisions through MB0 rather than assuming all prose is editable.
4. Review all five owning plans and dependency edges together; preserve independent
   Network/Narrator delivery and production seed/TITAN blockers honestly.
5. Approve clean-base/worktree creation and focused OpenSpec changes separately.
   No implementation, rollout flag change, installed-campaign import or producer-side
   modification is authorized merely by accepting this planning document.

Success is a complete distinctive adventure entering one remembered, causally
coherent campaign whose future remains open to the players, not the amount of
content generated or the frequency with which TITAN changes it.
