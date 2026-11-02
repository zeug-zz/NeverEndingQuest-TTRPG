# V2 Narrative Overview (Program Index)

Status: Cross-track index and sequencing reference; not implementation authorization.
Date: 2026-10-30. Updated 2026-11-03: overriding experience goal (s2), Track F
Spatial, and a revised start of Network plus mapping pilot first (s7).
Replaces: `plans/archive/v2-narrative-track.md` (2026-03-09 cohesion spine, its
phase map, "Next Milestone" and exit criteria). Archived/ADR links to the old
path remain provenance only.

## 1. Purpose and authority

This index lists the v2 master plans, what each owns, which shared contracts each
provides, and the build sequence. It owns no requirements.

The initial planning set now comprises Network, Narrator, Memory Pilot, TITAN,
Module Builder and Spatial (mapping pilot plus spatial master plan). It is assembled for whole-program owner review, not approved for
execution. Review precedes clean-base verification, worktree creation and focused
OpenSpec implementation authorization; no goal or worktree is started by this index.

Precedence: `AGENTS.md` > accepted ADRs > active OpenSpec changes > master plans >
this index. Conflicts are resolved in the owning plan or by ADR, never here.
OpenSpec implementation authorization remains explicit per change.

## 2. Overriding experience goal and prime directive (ADR-0007)

**Overriding goal of the whole v2 upgrade: optimize gameplay UX in the theatre of
the players' mind.** Every player, at the table or on a thin client, should be
able to picture and inhabit the same coherent, persistent world. The world
should remember the people, places, choices and consequences that matter to the
players, and respond to them with believable intelligence.

Each track serves that goal:

| Track | Contribution |
| --- | --- |
| Network | Brings remote players into the same scene |
| Narrator | Supplies the attentive "sentient ghost in the machine" who remembers |
| Spatial | Makes the world an imaginable, stable place |
| Memory Pilot and TITAN | Give the world continuity and a life of its own |
| Builder | Supplies coherent places and stories to play |

Technical success (correct state, smaller prompts, passing tests) is necessary
but never sufficient. A plan or gate that improves mechanics while making the
imagined experience worse has not met this goal. "Close enough" is acceptable
where players cannot perceive the difference and no rule they rely on is broken.
Python authority below is what makes that imagined world trustworthy.

### 2.1 Interpretation guide for orchestrators and builders

The product is the picture each player holds: whether it is coherent, vivid,
shared and good enough to act on. JSON state, prompts and prose are means. The
art is the balance of determinism and indeterminism. Python is inflexible, which
suits concrete world facts. The LLM is flexible as human imagination is, which
suits open-ended play. Do not chase exhaustive Python accuracy: it constrains
creativity and never removes every deterministic bug.

1. Contradiction outweighs imprecision. Players notice a door that moves or a
   dead enemy that returns, not a vague distance. Spend determinism on
   consistency over time (stable IDs, canonical layouts, persisted changes,
   identical context across retries/transitions); stay "close enough" elsewhere.
   Measure contradiction across whole sessions, not single-turn accuracy.
2. The picture must be actionable. Context packets expose the choices on offer
   (exits, cover, sightlines, proximity); narration surfaces them in story terms.
   Free-text intent resolves to Python-validated actions so imagination and
   mechanics agree.
3. Python decides, the LLM shows. Commit new facts before narrating them. When
   data is missing, describe less rather than invent firm facts that will later
   be contradicted. Authority boundaries are unchanged.
4. Players see what their characters perceive. Projections are filtered by
   perception and knowledge; a multi-PC party may hold different pictures, and
   switching focus PC switches viewpoint.
5. Context is a curated scene, not an archive. Bounded packets cut tokens and
   latency; long pauses break the scene, so latency budgets are UX requirements.
6. Visual aids support the imagined scene and never replace it. Prose stays
   primary; a map that contradicts narration is the bug.

For the LLM-led build itself: green tests prove the scaffolding, not the
experience; live captures and human ratings decide UX gates. Every feature
states what a player would notice if it were missing or wrong; a feature that
changes neither what players imagine nor what they can do is cost without
benefit. Do not optimize the easiest metric (schema validity, test counts,
one-shot accuracy). When fidelity and flow conflict, choose what players
experience, but never by moving authority from Python to the LLM.

Prime directive:

1. Python is world-reality authority. Memory, summaries and model output never
   mutate mechanical state by assertion.
2. Runtime LLM creativity adapts framing, NPCs and hooks within Python truth.
3. Proposal -> Python validation -> approval -> commit -> disclosure. Failed
   checks quarantine with deterministic remediation.
4. Canon apply: ADR-0027 (blanket human approval before canon apply) is
   deprecated by owner decision (2026-10-28); it belonged to the retired
   Titan/EGO "self-improving" concept. A superseding ADR recording TITAN's staged
   policy approval is a TITAN P0 deliverable. Until that ADR is accepted, no
   automatic canon apply ships. Narrator derived artifacts (packets, agendas,
   summaries) are not canon and are unaffected.

## 3. Shared terms

- Knowledge classes: seed possibility, committed fact/event, attributed
  belief/report, conditional intention (agenda/forecast). Never interchangeable.
- Scope: authored world/module version, campaign instance, worldline, effective
  generation (fencing identity on restore/import/reset), perspective ID.
- Scoped gateway: server-resolved retrieval authorization; unknown scope fails closed.
- Continuity anchors, Archivist packet, committed event envelope: see
  `plans/v2-narrator.md` s7.
- `continuity_contract`, strict / warn-first mode: module ingest (unchanged).
- Adventure blueprint: reviewed reusable authored module model; its human-DM and
  NEQ/TITAN presentations must agree. Campaign bindings and played consequences
  are scoped runtime records, not edits to reusable authored history.
- Seed DB: versioned read-only producer artifact (`data/world_narrative_seed.db`).
  Never merged into a populated campaign DB by bootstrap; see
  `plans/v2-memory-pilot.md`.
- Spatial projection: a Python-built, audience-scoped view of one spatial truth.
  Audiences are the Narrator packet, combat packet, actor view and player map.
  Views agree on shared facts and are knowledge-filtered. See `plans/v2-spatial.md`.
- Schematic versus metric: display layout positions are schematic. Distances and
  travel times come only from authored or derived metric data, or are unknown.
- Scene layout: authored per-location anchors, features (with obstruction, sight,
  cover and hazard properties), exit sides, sightlines and zone hints. It
  replaces the template `tactical_grid`.
- Spatial overlay: campaign-scoped changes to reusable module space (feature
  state, discovered/visited, known exits) that persist across combat,
  transitions and save/restore.
- Zone ledger: Python's theatre-of-the-mind combat positions, made of named zones
  and engaged, near, far and out-of-sight bands.

## 4. Plan ownership

| Plan | Owns | Status |
| --- | --- | --- |
| `plans/archive/combat-openrouter-alignment.md`, `plans/archive/openrouter_llm_router_architecture.md` | LLM router and combat refactor | Completed verified baseline |
| `plans/v2-server-client-network.md` | Player boundary, React `/client`, OpenTunnel, N0-N4 | Track A |
| `plans/v2-narrator.md` | Narrator Hindsight, event envelope, gateway, Archivist, agendas, portability, P0-P6 | Track B |
| `plans/v2-memory-pilot.md` | Seed import/retrieval, evidence/knowledge substrate, TITAN seams, P0-P6 | Track C |
| `plans/v2-titan-game-engine.md` | Five-head engine, alignment ledger, interventions, personification, P0-P6 | Track D |
| `plans/v2-module-builder.md` | Faithful source model, reviewed adaptation, seed-enriched playable blueprint, DM presentation, campaign binding and TITAN consumer, MB0-MB5 | Track E; companion producer, not a second engine |
| `plans/v2-mapping-pilot.md` | Live Capture Arena spatial research: arms A/B/D, theatre-of-the-mind zone ledger, layout feasibility, map sketches, decision gate SP0-SP4 | Track F research; first Track F worktree |
| `plans/v2-spatial.md` | Spatial authority and projections, exploration and Narrator spatial phases S1-S5, spatial combat SC0-SC4 | Track F; provisional on the pilot gate |
| `plans/version-2/mapping/*` (six drafts) and `map-review-oct26.md` | Earlier mapping designs; deliberation record | Superseded reference; the review stays the deliberation record |
| `plans/neq-world-handover.md` | Seed producer contract | External dependency |
| `plans/v2-memory-draft.md` | Provisional reference; companion relationship migration | Reference; Narrator/pilot win on overlap |
| `plans/archive/module-import.md` | Historical continuity baseline and scaled-import proposals | Archived reference; bulk inventory, progression and continuous import remain deferred and require a separately reviewed plan; reconcile campaign-history wording in Builder MB0 |
| `plans/version-2/world-narrative.md`, `plans/version-2/journal.md`, `plans/version-2/CNS build/EGO.md`, `plans/backstage-agents.md` | Independent or speculative | Not prerequisites |

## 5. Shared contracts (one owner each)

| Contract | Owner | Consumers |
| --- | --- | --- |
| Committed event envelope / commit identity (on combat turn receipts) | Narrator P1 | Network transcript ordering, Pilot P3, TITAN, Builder MB3 |
| Campaign/worldline/effective-generation fencing, save manifest | Narrator P2 | Pilot P3/P5, TITAN s14, Builder MB3/MB5 |
| Scoped gateway and perspective policy | Narrator P2/P3 | TITAN fan-out (reserved permissions) |
| Agenda records and revisions | Narrator P5 | TITAN P3; Builder conditional records when published as agendas |
| Seed catalogue, import manifest, bounded seed retrieval | Pilot P1/P2 | TITAN P1, Builder MB2; production-seed release claims also require Pilot P6 |
| Evidence/knowledge classes, seed instantiation (extends the Narrator envelope) | Pilot P3 | TITAN P1-P5, Builder MB3 |
| Alignment ledger and rubric | TITAN P2 | -- |
| Canon-apply policy ADR (supersedes ADR-0027) | TITAN P0 | TITAN P3+, Builder campaign-binding/consumer policy |
| Faithful source/adaptation ledger and reusable blueprint | Builder MB1/MB2 | DM and NEQ presentations, campaign binding, TITAN P4/P5 consumer |
| Existing continuity contract extensions and module-version binding adapter | Builder MB0/MB3, preserving ingest contracts | Pilot/TITAN continuity seams; later bulk import |
| Campaign module-continuity projections | Builder MB3 using Narrator event/fencing and Pilot evidence APIs | Narrator/TITAN; derived notes only, not Archivist expansion or a required new Historian |
| Typed intervention operations, risk and publication validators | TITAN P0/P4 | Builder MB4 maps blueprint permissions/dependencies; metadata grants no write authority |
| Player projection and sync protocol | Network P1 | Narrator status (host-only) |
| Managed companion process supervision (Hindsight/PostgreSQL, OpenTunnel) | Joint decision at Network N0 / Narrator P0 | Both |
| Spatial authority and projections ADR | Track F (drafted at pilot SP4; accepted before S1 starts) | All spatial consumers |
| Spatial identity and `SpatialService` query API | Spatial S1 | Narrator P3/P4, TITAN, Builder, combat SC1 |
| Scene layout schema | Spatial S1 (pilot draft) | Builder MB1/MB2 produce it; S3 backfill; SC1 zones |
| Spatial overlay and discovery state | Spatial S1, using Narrator P1 events and P2 save manifest/fencing | Narrator, TITAN, Builder MB3, S4 |
| Narrator spatial packet | Spatial S2 | Narrator P4 layered assembler (current-state region) |
| Player map projection | Spatial S4, as a message within the Network P1 protocol | `/client`, host tab |
| Encounter spatial state, typed `position_deltas` | Spatial SC1, extending combat turn receipts | Tactical brain, ally controller, Narrator P1 commit identity |
| Regional geography | Spatial S5 (separate plan first) | TITAN, Builder MB3 |
| `memory.db` migration chain | Serialized by merge order | All |

## 6. Dependency graph

```text
B0: router + combat refactor committed (incl. llm-router-cleanup,
    combat-ally-controller), reviewed/merged clean base on origin,
    completed active changes archived, exact base SHA recorded
 |-- Track A  Network N0..N4 -> invited human testers on thin clients
 |-- Track F  Mapping pilot SP0..SP4 (research; worktree S alongside Network)
 |     pilot gate + spatial ADR -> S1 foundation (event wiring after Narrator P1;
 |       overlay joins the Narrator P2 save manifest)
 |     S1 -> S2 Narrator spatial packet -> consumed by Narrator P4
 |     S2 + Network N2 -> S4 shared player map (tester follow-up cohort)
 |     S1 + Builder MB1/MB2 -> S3 authored layouts (backfill only if pilot D1 passes)
 |     S1 + SC0 contracts -> SC1 zone ledger -> SC2 tactics -> SC3 intent ; + S4 -> SC4
 |     S4 + SC2 + TITAN P0 + a separate regional plan -> S5 regional layer
 |-- Track B  Narrator P0 (docs in main) ; worktree R opens after the pilot gate
 |     P0..P6
 |     P1 merged  -> Track C Pilot P1-P2  (Pilot P0 is docs/audit; may start before B0)
 |     P2 passed  -> Pilot P3 -> P4 -> P5 ; Pilot P6 waits on producer full export
 |-- Track D  TITAN P0 contracts + superseding ADR (after Pilot P0, alongside Narrator P2)
 |     TITAN P1 = delivered by Pilot P2-P4 ; TITAN P2 ledger after Pilot P3
 |     TITAN P3+ after Narrator P5 and Pilot P4 ; TITAN P6 live may use Track A clients
 |-- Track E  Builder MB0 -> MB1 -> MB2 blueprint/presentation with fixtures
       Pilot P1/P2 -> MB2 real seed retrieval ; Pilot P6 -> enriched release clearance
       Narrator P1/P2 + Pilot P3 -> MB3 campaign binding/continuity
       Narrator P5 -> any published conditional agendas
       MB3 + TITAN P0/P3/P4 -> MB4 ; TITAN P5 -> personification scenarios
       MB4 + TITAN P6 + Narrator/Pilot portability -> MB5 joint acceptance
Deferred: offline LAN, Windows host, allied-NPC agents, EGO/RATIO/CNS.
```

## 7. Development timeline (worktrees)

Durations are planning estimates; gates, not dates, decide completion. Week 0 is
2026-10-28. Worktree handling follows `.opencode/skills/neq-worktrees/SKILL.md`;
each worktree is created only with owner approval after B0 lands.
The existing week bands below remain estimates, not promises of staffing or new
Builder delivery dates. Builder work uses the dependency windows in section 8.1;
no calendar estimate overrides a shared-contract or release gate.

Revised 2026-11-03 (owner decision). The build opens with two concurrent
worktrees: Network, so human testers arrive as early as possible, and the
mapping pilot, because spatial decisions shape the Narrator's context, combat
and the Builder's output. Narrator P0 proceeds as docs in the main checkout.
Worktree R opens after the pilot gate. This moves Narrator delivery about five
weeks later than the 2026-10-30 timeline; Network and the tester date are
unchanged.

| Weeks | Main checkout | Worktree N `feature/v2-network` | Worktree S (Spatial) | Worktree R `feature/v2-narrator` | Memory / TITAN |
| --- | --- | --- | --- | --- | --- |
| 0-2 | Stage 0 (B0): push the local commits to `origin` through reviewed PRs, archive completed changes, record B0 SHA. Pilot SP0 preregistration (docs); supersede `mapping-research-arena-comparison`; owner rates the 36 Stage 1 packets | -- | -- | -- | Pilot P0 (docs + read-only audit of `tmp/` copies); send producer request early; reconcile TITAN s3 seed facts |
| 2-3 | Narrator P0 contracts and budgets (docs); draft event envelope jointly with network | N0 feasibility | `feature/v2-mapping-pilot`: SP1 tooling | -- | Pilot P0 complete |
| 3-5 | Narrator P0 complete; index/ADR upkeep | N1 security and protocol | SP2 offline (D1 layouts, M1 sketches); SP3 live matrix, serialized on port 8360 | -- | -- |
| 5-8 | Pilot decision gate (about week 5-6); spatial ADR; `plans/v2-spatial.md` moved from provisional to decided | N2 React vertical slice | SP4 report, then `feature/v2-spatial`: S1 foundation | Opens after the pilot gate: P1 events -> merge PR (rebase N and S) | -- |
| 8-10 | | N3 packaging -> N4 live; testers around week 10 | S1 event wiring (after Narrator P1 merges) -> S2 Narrator spatial packet | P2 Hindsight and portability (largest phase); rebase onto S2 | Worktree M `feature/v2-memory-pilot` after Narrator P1 merges: Pilot P1-P2. TITAN P0 contracts + superseding ADR (docs) |
| 10-13 | Tester feedback fixes; retire worktree N | -- | S2 live gate -> S4 shared player map (Network N2 merged); SC0 combat contracts (docs) | P2 continues | Pilot P1-P2 continue |
| 13-16 | Second tester cohort with the shared map | -- | S3 authored layouts with Builder; worktree SC `feature/v2-spatial-combat`: SC1-SC2 | P3 retrieval | Pilot P3 (after Narrator P2) |
| 16-19 | | | SC3-SC4 intent, combat map, live gates | P4 Archivist (consumes the S2 packet) | Pilot P4-P5; TITAN P2 ledger |
| 19-22 | | | Regional (S5) plan | P5 agendas, P6 live; human testers on thin clients cover multi-session continuity scenarios | Pilot P6 when the producer delivers |
| 22+ | | | S5 build alongside TITAN | -- | TITAN P3-P6 in worktree T |

### Goals (one per worktree)

| Worktree | Goal objective | Notes |
| --- | --- | --- |
| N | Network N0-N4 delivered to invited testers | Tester builds come from a tagged `main` SHA |
| S `feature/v2-mapping-pilot` | Objective and immutable completion criteria of `plans/v2-mapping-pilot.md` s11, verbatim | Opens with N after B0; research only; ends at the owner decision gate |
| SB `feature/v2-spatial` | S1-S4 objective of `plans/v2-spatial.md` s11 | After the pilot gate; may reuse worktree S once the pilot branch merges |
| SC `feature/v2-spatial-combat` | SC0-SC4 objective of `plans/v2-spatial.md` s11 | After S1 merges and SC0 is accepted |
| R | Objective and immutable completion criteria of `plans/v2-narrator.md` s17, verbatim | Opens after the pilot gate; P0 runs as docs in main beforehand |
| M | Candidate objective of `plans/v2-memory-pilot.md` s4 | Full-seed criterion may end BLOCKED on the producer; report it, never drop it |
| T (later) | TITAN P0 and P2-P6; P1 recorded as delivered by the pilot | Separate goal so a blocked pilot does not hold the engine open |
| B `feature/v2-module-builder` | Candidate objective and full completion criteria of `plans/v2-module-builder.md` s8/s9 | Create only after owner approval and B0; MB0-MB2 may precede TITAN runtime, but full completion retains seed/MB3-MB5 gates |

### Parallel-worktree rules

- Each worktree has its own `.venv`; the owner provides `config.py`. Never copy secrets.
- Ports never collide: the network dev player listener gets a new port (not 8357
  or 8360); Hindsight/PostgreSQL namespaces are per worktree; live captures are
  serialized on port 8360 regardless of worktree.
- Small PRs per phase; rebase the other worktree after each merge. The narrator
  branch stays out of `web/` until Network N2 merges. Expect
  `requirements-lock.txt` conflicts.
- Spatial file ownership:
  - The mapping pilot stays in `scripts/` capture tooling, sandbox fixtures and
    `tmp/`. Any core hook needs explicit owner approval (pilot plan s5.3).
  - S2 owns the `main.py` DM-note exits block and the
    `core/ai/conversation_utils.py` atlas injection first. The Narrator
    rebases P3/P4 onto it.
  - `core/combat/` changes belong to the SC worktree only.
  - S4 and SC4 touch `web/` and `/client` only after Network N2 merges, and only
    through the Network protocol.
- Live captures are serialized: the pilot's SP3 matrix window must not overlap
  Network or other gates on port 8360.
- Builder host/toolkit changes coordinate with Network's `web/` ownership; review
  controls stay host-only. Early source/model work can avoid that shared surface.
  Builder bindings consume Narrator/pilot APIs, never a competing migration chain.
- Keep the planning checkout and pre-existing draft intact until owner review.
  Do not transplant dirty work or existing goals into implementation worktrees.
- The existing `fix/gameplay-audit-20261023` worktree is outside this program;
  the owner will reuse it for an audit goal after the v2 builds are stable.

## 8. Memory pilot and TITAN together

The pilot goes first between the two, but in slices and after the Narrator's
foundations:

- The pilot is effectively TITAN's seed/P0 verification plus P1 substrate. Track
  it that way rather than building it twice.
- Pilot P0 (docs/audit, producer request) starts immediately.
- Pilot P1-P2 wait for Narrator P1 so the `memory.db` migration chain has one
  merge order.
- Pilot P3 waits for Narrator P2 and extends the Narrator event envelope and
  fencing rather than defining a rival model.
- TITAN P0 (contracts + superseding ADR) is written alongside Pilot P0 and
  Narrator P2; TITAN runtime (P3+) needs Narrator P5 and Pilot P4.
- After Pilot P0 lands, `plans/v2-memory-draft.md` is reference-only.

### 8.1 Module Builder alongside TITAN and the other tracks

The builder is a companion producer track, not a wholesale expansion of TITAN P4
and not a prerequisite for all engine work. Its detailed phase/OpenSpec outlines,
failure policies and gates live in `plans/v2-module-builder.md` sections 7-9.

| Dependency window | Builder work | Owning-track coordination |
| --- | --- | --- |
| Whole-plan review; before B0 | Read-only audit and manual prototype design only | Choose rights-clear source/second-module link and shared quality exemplar; no runtime authorization |
| After B0 and per-change approval | MB0 baseline closure/contracts, then MB1 faithful source/review | Reconcile accurate-ingest versus advisory adaptation, known test drift, continuity versioning and old import wording |
| Alongside early Narrator/pilot/TITAN contracts | MB2 blueprint and readable/machine projections with labelled fixtures | No requirement to wait for live heads; consume Pilot P1/P2 when delivered rather than implementing another seed reader |
| Narrator P1/P2 and Pilot P3 available | MB3 campaign bindings and continuity projections | Shared identity/commit/fencing/save APIs; consume Narrator P5 if publishing agendas; coordinate Pilot P4 continuity scenarios |
| TITAN P0 operation/policy contract, P3 scheduling, P4 publication | MB4 exact blueprint-to-operation adapter | TITAN owns risk/validators and dependency-safe publication; actor examples additionally require P5 lazy personification |
| TITAN P6 and Narrator/pilot portability ready | MB5 integrated cross-module, divergence and restore gates | Shared immutable evidence may satisfy separately judged ledgers; Pilot P6 full public-seed verification is still a release dependency |

TITAN P0 should review the producer/consumer boundary alongside its existing
operation inventory; P4 consumes dependency/permission metadata; P5 consumes
lightweight actor foundations; P6 exercises the joint scenarios. Existing phase
criteria and engine non-goals are not renumbered, weakened or marked complete.
The later focused OpenSpec changes must reconcile these interfaces in their owning
plans/contracts before code; this index does not silently expand those requirements.

TITAN may implement against legacy modules and contract fixtures before MB2 ships.
Narrator and Network remain independently deliverable. Shared authored setting
relationships never mean shared played events across campaigns. Full lazy actor
dossiers remain TITAN-owned; continuity-note maintenance does not require a new
Historian agent or change the Archivist's compaction responsibility.

Later bulk inventory, ZIP intake, progression ladders, scheduled imports and optional
world-profile overlays remain deferred proposals in the archived import reference,
not completed work or an authorized active track. Establish a reviewed successor
plan before implementation and reuse the reviewed builder lane; do not make bulk
throughput an MB1 prerequisite.

### 8.2 Spatial alongside the other tracks

Spatial is a cross-cutting track. The pilot decides representation, combat
granularity and enforcement, and the data pipeline. The build then supplies one
spatial truth to every consumer. Details live in `plans/v2-spatial.md` s8.

| Track | Seam | When |
| --- | --- | --- |
| Narrator | S1 movement/discovery events on the P1 envelope; overlay in the P2 save manifest and fencing; S2 packet as a P4 current-state region; stable location IDs for P3 recall | P0 records the seams; R rebases onto S2 |
| Network | Player map projection as a P1 protocol message; S4 panel after N2; second tester cohort rates the map | N1 reserves the message type; S4 after N2 |
| Combat baseline | SC0 reconciles `combat-tactical-cover`, `combat-turn-receipt-model`, `combat-tactical-brain` and ally contracts; SC4 reruns affected archived gates | After S1 |
| Builder | MB1/MB2 emit scene layouts, route data and feature IDs to the S1 schema; MB3 binds overlays and placements | MB0 adopts the schema draft from SP4 |
| TITAN | Spatial queries for interventions; S5 geography for fronts, weather and news | TITAN P0 records the seam; S5 later |

The spatial pilot does not wait for Narrator P1. It is research and touches no
shared runtime path. The spatial build (S1 onward) consumes Narrator contracts
rather than defining rival event or save models.

## 9. Index health checks

1. Each master plan links here and matches s4/s5.
2. Each shared contract has exactly one owner.
3. No plan contradicts an accepted ADR without a superseding ADR (ADR-0027 ->
   TITAN P0 ADR).
4. Dated facts are reconciled (TITAN s3 seed hash vs `plans/v2-memory-pilot.md` s3).
5. Builder source fidelity, reviewed adaptation, seed enrichment, module publication
   and campaign commitment are separate claims; fixtures and safe failed smoke runs
   do not satisfy production-seed or successful live-release gates.
6. The seven-plan review set (now including Track F) is complete as planning
   input only. B0, worktrees, goals, OpenSpec implementation and
   installed-campaign operations still require their explicit approvals; no track
   is reported delivered because its plan exists.
7. Spatial claims are kept separate:
   - pilot research versus production behavior;
   - prompt-only, offline and live evidence;
   - schematic layout versus metric distance;
   - observed versus enforced legality.

   `plans/v2-spatial.md` stays marked provisional until the pilot gate is
   recorded.
8. The owning plans adopt their Track F seams (s8.2) at their next review:
   Narrator P0, Network N1, Builder MB0 and TITAN P0. Until then, this index
   records each seam without expanding those plans' requirements.
9. Every track's acceptance includes the overriding experience goal (s2).
   Technical gates that worsen the imagined experience are not a release.

