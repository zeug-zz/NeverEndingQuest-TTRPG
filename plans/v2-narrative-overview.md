# V2 Narrative Overview (Program Index)

Status: Cross-track index and sequencing reference; not implementation authorization.
Date: 2026-10-30.
Replaces: `plans/archive/v2-narrative-track.md` (2026-03-09 cohesion spine, its
phase map, "Next Milestone" and exit criteria). Archived/ADR links to the old
path remain provenance only.

## 1. Purpose and authority

This index lists the v2 master plans, what each owns, which shared contracts each
provides, and the build sequence. It owns no requirements.

The initial planning set now comprises Network, Narrator, Memory Pilot, TITAN and
Module Builder. It is assembled for whole-program owner review, not approved for
execution. Review precedes clean-base verification, worktree creation and focused
OpenSpec implementation authorization; no goal or worktree is started by this index.

Precedence: `AGENTS.md` > accepted ADRs > active OpenSpec changes > master plans >
this index. Conflicts are resolved in the owning plan or by ADR, never here.
OpenSpec implementation authorization remains explicit per change.

## 2. Prime directive (ADR-0007)

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

## 4. Plan ownership

| Plan | Owns | Status |
| --- | --- | --- |
| `plans/archive/combat-openrouter-alignment.md`, `plans/archive/openrouter_llm_router_architecture.md` | LLM router and combat refactor | Completed verified baseline |
| `plans/v2-server-client-network.md` | Player boundary, React `/client`, OpenTunnel, N0-N4 | Track A |
| `plans/v2-narrator.md` | Narrator Hindsight, event envelope, gateway, Archivist, agendas, portability, P0-P6 | Track B |
| `plans/v2-memory-pilot.md` | Seed import/retrieval, evidence/knowledge substrate, TITAN seams, P0-P6 | Track C |
| `plans/v2-titan-game-engine.md` | Five-head engine, alignment ledger, interventions, personification, P0-P6 | Track D |
| `plans/v2-module-builder.md` | Faithful source model, reviewed adaptation, seed-enriched playable blueprint, DM presentation, campaign binding and TITAN consumer, MB0-MB5 | Track E; companion producer, not a second engine |
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
| `memory.db` migration chain | Serialized by merge order | All |

## 6. Dependency graph

```text
B0: router + combat refactor committed (incl. llm-router-cleanup,
    combat-ally-controller), reviewed/merged clean base on origin,
    completed active changes archived, exact base SHA recorded
 |-- Track A  Network N0..N4 -> invited human testers on thin clients
 |-- Track B  Narrator P0..P6
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

| Weeks | Main checkout | Worktree N `feature/v2-network` | Worktree R `feature/v2-narrator` | Memory / TITAN |
| --- | --- | --- | --- | --- |
| 0-2 | Stage 0 (B0): finish router/combat changes, commit dirty tree as reviewable PRs, push local commits to `origin`, archive completed changes, record B0 SHA | -- | -- | Pilot P0 (docs + read-only audit of `tmp/` copies); send producer request early; reconcile TITAN s3 seed facts |
| 2-3 | Index/ADR upkeep | N0 feasibility | P0 contracts and budgets; draft event envelope jointly with network | Pilot P0 complete |
| 3-5 | | N1 security and protocol | P1 events -> merge PR (rebase N) | -- |
| 5-8 | | N2 React vertical slice | P2 Hindsight and portability (largest phase) | Worktree M `feature/v2-memory-pilot` after Narrator P1 merges: Pilot P1-P2. TITAN P0 contracts + superseding ADR (docs) |
| 8-10 | | N3 packaging -> N4 live; testers around week 10 | P3 retrieval | Pilot P3 (after Narrator P2) |
| 10-13 | Tester feedback fixes; retire worktree N | -- | P4 Archivist | Pilot P4-P5; TITAN P2 ledger |
| 13-16 | | | P5 agendas, P6 live; human testers on thin clients cover multi-session continuity scenarios | Pilot P6 when the producer delivers |
| 16+ | | | -- | TITAN P3-P6 in worktree T |

### Goals (one per worktree)

| Worktree | Goal objective | Notes |
| --- | --- | --- |
| N | Network N0-N4 delivered to invited testers | Tester builds come from a tagged `main` SHA |
| R | Objective and immutable completion criteria of `plans/v2-narrator.md` s17, verbatim | -- |
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

## 9. Index health checks

1. Each master plan links here and matches s4/s5.
2. Each shared contract has exactly one owner.
3. No plan contradicts an accepted ADR without a superseding ADR (ADR-0027 ->
   TITAN P0 ADR).
4. Dated facts are reconciled (TITAN s3 seed hash vs `plans/v2-memory-pilot.md` s3).
5. Builder source fidelity, reviewed adaptation, seed enrichment, module publication
   and campaign commitment are separate claims; fixtures and safe failed smoke runs
   do not satisfy production-seed or successful live-release gates.
6. The five-plan review set is complete as planning input only. B0, worktrees,
   goals, OpenSpec implementation and installed-campaign operations still require
   their explicit approvals; no track is reported delivered because its plan exists.
