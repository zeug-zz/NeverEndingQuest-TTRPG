# V2 Narrative Overview (Program Index)

Status: Cross-track index and sequencing reference; not implementation authorization.
Date: 2026-10-30. Updated 2026-11-03: overriding experience goal (s2), Track F
Spatial, and a revised start of Network plus mapping pilot first (s7).
Updated 2026-11-04: Track G Firelight rules engine and phased context
compression (s8.3, s8.4); owner decisions in `plans/v2-firelight.md` s2.
Updated 2026-11-05: owner approval to start the build; B0 recorded; worktrees
N and S approved; build ledger and goal prompts (s10).
Replaces: `plans/archive/v2-narrative-track.md` (2026-03-09 cohesion spine, its
phase map, "Next Milestone" and exit criteria). Archived/ADR links to the old
path remain provenance only.

## 1. Purpose and authority

This index lists the v2 master plans, what each owns, which shared contracts each
provides, and the build sequence. It owns no requirements.

The initial planning set now comprises Network, Narrator, Memory Pilot, TITAN,
Module Builder, Spatial (mapping pilot plus spatial master plan) and Firelight.
On 2026-11-05 the owner approved starting the build: B0 and worktrees N and S
with one goal each, recorded in the build ledger (s10). Every other worktree,
goal and installed-campaign operation still needs its own approval; this index
starts nothing by itself.

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
| Firelight | Keeps the party's coins, gear, charges and resources from contradicting themselves |

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
- Rules engine: the pinned Firelight binary, a stateless deterministic function
  the Python host calls. It is not a store; canonical owners are unchanged.
- Engine receipt: a committed transaction's revision, request id and typed
  before/after events. Refusals are typed diagnostics.
- Live-state document: the campaign-scoped record of what only the engine writes
  (occupants, quest logs, map position and state, clock), stored atomically by
  the host.
- Family registry: per rule family, whether Python, shadow or the engine
  decides. See `plans/v2-firelight.md` s6.4.

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
| `plans/v2-firelight.md` | Firelight rules engine under Python host authority: ADR, pin and upgrade policy, bridge, shadow, family cutovers G0-G6 and GU; phased context compression | Track G |
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
| Player projection and sync protocol | Network N1 | Narrator status (host-only) |
| Managed companion process supervision (Hindsight/PostgreSQL, OpenTunnel) | Joint decision at Network N0 / Narrator P0 | Both |
| Spatial authority and projections ADR | ADR-0034, accepted 2026-11-09 | All spatial consumers |
| Spatial identity and `SpatialService` query API | Spatial S1 | Narrator P3/P4, TITAN, Builder, combat SC1 |
| Scene layout schema | Spatial S1 (pilot draft) | Builder MB1/MB2 produce it; S3 backfill; SC1 zones |
| Spatial overlay and discovery state | Spatial S1, using Narrator P1 events and P2 save manifest/fencing | Narrator, TITAN, Builder MB3, S4 |
| Narrator spatial packet | Spatial S2 | Narrator P4 layered assembler (current-state region) |
| Player map projection | Spatial S4, as a message within the Network N1 protocol | `/client`, host tab |
| Encounter spatial state, typed `position_deltas` | Spatial SC1, extending combat turn receipts | Tactical brain, ally controller, Narrator P1 commit identity |
| Regional geography | Spatial S5 (separate plan first) | TITAN, Builder MB3 |
| Firelight ADR, pin record and upgrade policy | Track G0 | All tracks; `AGENTS.md` rule on acceptance |
| Firelight bridge, world projection, live-state document and family registry | Track G2 | Narrator P1/P2 (receipts, save manifest, fencing), SC combat bookkeeping, Network views, TITAN operations |
| Rule-family cutovers and retirement of matching guards and validator sections | Track G3-G6 | Validator and prompt owners |
| Context views (compact evidence, one mention per fact, typed history markers) | `v2-context-views` (s8.4) | Narrator P4, Spatial S2 |
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
 |-- Track G  Firelight G0 ADR (docs in main; accepted before Narrator P0
 |     ratifies the envelope) ; G1 offline spike (scripts/tmp)
 |     G0 + G1 gate + pilot SP3 done -> worktree G: G2 bridge + shadow
 |     G2 -> G3 new capabilities (storage, trade, charges) -> G4 inventory/AC
 |     G4 + SC0 -> G5 resources/conditions/clock (combat bookkeeping SC-owned)
 |     G5 -> G6 progression/quests/occupants ; GU per upstream release
 |-- Track B  Narrator P0 (docs in main) ; worktree R opens after the Narrator P0 gate (OD-2, 2026-11-10)
 |     P0..P6
 |     P1 merged  -> Track C Pilot P1-P2  (Pilot P0 is docs/audit; may start before B0)
 |     P2 passed  -> Pilot P3 -> P4 -> P5 ; pilot + MB2 evidence -> schema sign-off
 |     signed-off schema + separate producer authorization -> full export -> Pilot P6
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
Worktree R opens after the pilot gate [superseded 2026-11-10: OD-2 moves this to the Narrator P0 gate]. This moves Narrator delivery about five
weeks later than the 2026-10-30 timeline; Network and the tester date are
unchanged.

Revised 2026-11-10 (owner decisions OD-1 to OD-12, s10.1). Actual dates: B0
and N0/SP0/SP1/G0 on 2026-11-05 (week 1); N1 and SP2/SP3 2026-11-06 (week 1);
N2 implementation merged 2026-11-07 (bands said weeks 5-8); ADR-0034 accepted
2026-11-09. The week bands below are now HISTORICAL estimates. The governing
order is gate-keyed, from the [V2 fable review](v2-fable-review.md) s6:

```text
Wave 0  ledger reconciliation | status lines + ID hygiene | AGENTS commands | archive finished pilot changes
        SP4 closeout under OD-1 -> S goal closes
Wave 1  main: test-runner-ci-tier ; live-gate preflight ; single-runtime unification
        main: Narrator P0 extended (envelope map, identity contract, seam map, compression and
              persistence inventories -> baseline after preflight and unification)
        main: Firelight G1 (budget ratified first) ; Memory Pilot P0 close
        N:    N2 gate -> N3
Wave 2  main: context-views step 1 (byte-identical prompt seam) -> step 2 ; atomic writes
        R:    Narrator P1 (PR1 identity -> PR2 envelope -> PR3 backfill)
        S/SB: S1a (after SP4) -> S1b (format + P1 PR2)
        G:    G2 (G1 gate + identity contract + P1 PR1)
Wave 3  N: N4 testers ; SB: S2a ; G: G3 ; R: P2a -> P2b ; M: Pilot P1-P2
Wave 4+ as the owning plans order it (MB0-MB1 when review time allows)
```

Changes from the bands: R opens on the Narrator P0 gate; G opens on the G1
gate and the identity contract; S1a is separable from the format decision; one
identity contract and one prompt-assembly seam land before their consumers;
unification lands before the baseline. Live windows follow the fable review s7
rules (preflight before booking, driver-enforced caps, shared sessions under
OD-12, booking priority Network > baselines > track gates).

Historical week bands (2026-11-03 estimate):

| Weeks | Main checkout | Worktree N `feature/v2-network` | Worktree S (Spatial) | Worktree R `feature/v2-narrator` | Worktree G `feature/v2-firelight` | Memory / TITAN |
| --- | --- | --- | --- | --- | --- | --- |
| 0-2 | Stage 0 (B0) recorded 2026-11-05 (s10.1). After N and S launch: Firelight G0 ADR, pin and gap inventory (docs) | Opens 2026-11-05: N0 feasibility | `feature/v2-mapping-pilot` opens 2026-11-05: SP0 preregistration (docs PR); supersede `mapping-research-arena-comparison`; owner rates the 36 Stage 1 packets | -- | -- | Pilot P0 (docs + read-only audit of `tmp/` copies); prepare pilot feedback/schema review, not a full-corpus request; reconcile TITAN s3 seed facts |
| 2-3 | Narrator P0 contracts and budgets (docs); draft event envelope jointly with network; G0 ADR accepted before the envelope is ratified; G1 offline spike in `scripts/`/`tmp/` | N0 feasibility | `feature/v2-mapping-pilot`: SP1 tooling | -- | -- | Pilot P0 complete |
| 3-5 | Narrator P0 complete (with C7 block/cache logging baseline); index/ADR upkeep; G1 gate | N1 security and protocol | SP2 offline (D1 layouts, M1 sketches); SP3 live matrix, serialized on port 8360 | -- | -- | -- |
| 5-8 | Pilot decision gate (about week 5-6); spatial ADR; `plans/v2-spatial.md` moved from provisional to decided; `v2-context-views` after SP3 and the P0 baseline | N2 React vertical slice | SP4 report, then `feature/v2-spatial`: S1 foundation | Opens after the pilot gate: P1 events -> merge PR (rebase N and S) | Opens after SP3: G2 bridge and shadow | -- |
| 8-10 | | N3 packaging -> N4 live; testers around week 10 | S1 event wiring (after Narrator P1 merges) -> S2 Narrator spatial packet | P2 Hindsight and portability (largest phase); rebase onto S2 | G3 storage, trade, charged items (joins the tester build only if merged before the tagged SHA) | Worktree M `feature/v2-memory-pilot` after Narrator P1 merges: Pilot P1-P2. TITAN P0 contracts + superseding ADR (docs) |
| 10-13 | Tester feedback fixes; retire worktree N | -- | S2 live gate -> S4 shared player map (Network N2 merged); SC0 combat contracts (docs) | P2 continues | G4 inventory, coins, equipment, AC cutover | Pilot P1-P2 continue |
| 13-16 | Second tester cohort with the shared map | -- | S3 authored layouts with Builder; worktree SC `feature/v2-spatial-combat`: SC1-SC2 (combat bookkeeping via the G bridge) | P3 retrieval | G5 resources, slots, rests, conditions, ammunition, clock cutover | Pilot P3 (after Narrator P2) |
| 16-19 | | | SC3-SC4 intent, combat map, live gates | P4 Archivist (consumes the S2 packet) | G6 progression, quests, occupants cutover | Pilot P4-P5; TITAN P2 ledger |
| 19-22 | | | Regional (S5) plan | P5 agendas, P6 live; human testers on thin clients cover multi-session continuity scenarios | Retire worktree G; GU upgrades as small changes in main | Schema sign-off after pilot/MB2 evidence; Pilot P6 only after separately authorized producer delivery |
| 22+ | | | S5 build alongside TITAN | -- | -- | TITAN P3-P6 in worktree T |

### Goals (one per worktree)

| Worktree | Goal objective | Notes |
| --- | --- | --- |
| N `feature/v2-network` | Network N0-N4 delivered to invited testers; full prompt in s10.5 | Tester builds come from a tagged `main` SHA |
| S `feature/v2-mapping-pilot` | Objective and immutable completion criteria of `plans/v2-mapping-pilot.md` s11, verbatim; full prompt in s10.5 | Opens with N after B0; owns SP0 (owner decision 2026-11-05); research only; ends at the owner decision gate |
| SB `feature/v2-spatial` | S1-S4 objective of `plans/v2-spatial.md` s11 | After the pilot gate (S1a may start after SP4 closeout, OD-9); may reuse worktree S once the pilot branch merges |
| SC `feature/v2-spatial-combat` | SC0-SC4 objective of `plans/v2-spatial.md` s11 | After S1 merges and SC0 is accepted |
| R | Objective and immutable completion criteria of `plans/v2-narrator.md` s17, verbatim | Opens after the Narrator P0 gate (OD-2, 2026-11-10); P0 runs as docs in main beforehand |
| M | Candidate objective of `plans/v2-memory-pilot.md` s4 | Full-seed criterion may end BLOCKED on the producer; report it, never drop it |
| T (later) | TITAN P0 and P2-P6; P1 recorded as delivered by the pilot | Separate goal so a blocked pilot does not hold the engine open |
| B `feature/v2-module-builder` | Candidate objective and full completion criteria of `plans/v2-module-builder.md` s8/s9 | Create only after owner approval and B0; MB0-MB2 may precede TITAN runtime, but full completion retains seed/MB3-MB5 gates |
| G `feature/v2-firelight` | Candidate goal of `plans/v2-firelight.md` s13 | After the G1 gate and the shared identity contract, with no frozen-configuration study in flight in S (OD-4, 2026-11-10); G0/G1 run in main and `tmp/` beforehand |

### Parallel-worktree rules

- Each worktree has its own `.venv`; the owner provides `config.py`. Never copy secrets.
- Ports never collide: the network dev player listener uses port 8370 (owner
  decision 2026-11-05; never 8357 or 8360); worktrees share the main repo's
  Hindsight bank by design (plugin `resolveWorktrees`); live captures are serialized on port 8360 regardless of
  worktree, booked through the ledger (s10.2).
- Small PRs per phase; rebase the other worktree after each merge. The narrator
  branch stays out of `web/` until Network N2 merges. Expect
  `requirements-lock.txt` conflicts.
- Spatial file ownership:
  - The mapping pilot stays in `scripts/` capture tooling, sandbox fixtures and
    `tmp/`. Any core hook needs explicit owner approval (pilot plan s5.3).
  - S2 owns the `main.py` DM-note exits block and the
    `core/ai/conversation_utils.py` atlas injection first. The Narrator
    rebases P3/P4 onto it.
  - `core/combat/` changes belong to the SC worktree only, including combat
    bookkeeping routed through the Firelight bridge.
  - S4 and SC4 touch `web/` and `/client` only after Network N2 merges, and only
    through the Network protocol.
- Firelight file ownership (`plans/v2-firelight.md` s10):
  - G1 stays in `scripts/` and `tmp/`; no runtime hook before worktree G.
  - G owns `core/rules/firelight/`, the `updates/` mechanics paths, the
    mechanics guards and prechecks, and the validator rules sections.
  - Worktree G opens only after pilot SP3, so the pilot's frozen production
    configuration is not disturbed.
  - `main.py` and the prompt files are shared hotspots with R and S2: small
    PRs, rebase after each merge.
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
- Pilot P0 (docs/audit, pilot feedback and schema-review preparation) starts
  immediately. The existing 240-fragment bundle is the evaluation input.
- Pilot P1-P5 and Builder MB2 supply evidence for bounded schema iteration
  with NEQ-world. Optimized schema sign-off precedes separate authorization
  of the roughly 40k-fragment production job. Pilot P6 verifies that later
  export; it does not block the pilot evaluation that informs its contract.
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

### 8.3 Firelight alongside the other tracks

Track G adopts upstream's public rules engine (Firelight Engine v0.1.0, by
Eternal Tavern) as a pinned binary behind a fork-native Python bridge. It
shares upstream's rules development without re-merging upstream code
(ADR-0031). Python stays host and canonical store; the engine decides legality
and bookkeeping for each family the registry has migrated. Details, owner
decisions and phases live in `plans/v2-firelight.md`.

| Track | Seam | When |
| --- | --- | --- |
| Narrator | Engine receipts supply commit identity to the P1 envelope; the live-state document joins the P2 save manifest; `expected_revision` supports fencing; committed engine events feed Hindsight retention | G0 hands the seam to P0, before the envelope is ratified |
| Spatial | The SP4 spatial ADR evaluates the engine map for S1 routes/visited places and S5 travel time; layout, zones and cover stay in Python | SP4, S1 |
| Combat / SC | Bookkeeping only (damage, healing, conditions, concentration, saves, resource spend); attack resolution and tactics stay in `core/combat/`; SC owns the change and reruns affected gates | SC0, with G5 |
| Network | Player views of inventory, storage and resources through the P1 projection; binary placement with N3 packaging | N1, N3 |
| Builder | MB1/MB2 emit route times, item catalogue and stock references | MB0 adopts the projection draft |
| TITAN | Mechanical intervention effects compile to engine actions and accept refusals | TITAN P0 |

The engine's journal and relationship families are not adopted; Narrator,
Pilot and TITAN keep those responsibilities unless a reviewed upgrade decides
otherwise.

### 8.4 Context compression, phased

Compression is not a separate build. The upstream README figures (92% system
prompt, 87% validation, 90%+ conversation) predate the fork, and the fork
already runs those techniques. The worthwhile upstream work is "context views"
and the removal of rules from prompts as Firelight takes them over. Ownership
is split across existing phases (`plans/v2-firelight.md` s9):

- Narrator P0: per-block byte counts and cached-token logging in the baseline.
- `v2-context-views` (main, or the first R task, after SP3 and the P0
  baseline): compact validator evidence, one mention per fact, fixed
  instructions in the system prompt, typed history markers.
- Spatial S2: atlas once per revision, one mention for exits and adjacency.
- Narrator P4: stable cacheable prefix and cache key; the Archivist replaces
  the old location and history summarisers; no silent truncation.
- Track G4-G6: each cutover removes its rules from prompts and the validator.

Budgets come from the fork's own P0 baseline. Story context is not compressed
at the cost of a less vivid shared picture (s2).

## 9. Index health checks

1. Each master plan links here and matches s4/s5.
2. Each shared contract has exactly one owner.
3. No plan contradicts an accepted ADR without a superseding ADR (ADR-0027 ->
   TITAN P0 ADR).
4. Dated facts are reconciled (TITAN s3 seed hash vs `plans/v2-memory-pilot.md` s3).
5. Builder source fidelity, reviewed adaptation, seed enrichment, module publication
   and campaign commitment are separate claims; fixtures and safe failed smoke runs
   do not satisfy production-seed or successful live-release gates.
6. The eight-plan review set (now including Tracks F and G) is planning input.
   Approvals granted so far are listed in s10.1; anything not listed there still
   needs explicit approval. No track is reported delivered because its plan
   exists or its goal is open; only a gate verdict in s10.3 records progress.
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
10. Firelight claims are kept separate: a family in shadow is not migrated; a
    pinned build that does not reproduce the upstream checksums is not adopted;
    a migrated family has its Python guard and validator section retired in the
    same change. The owning plans adopt their Track G seams (s8.3) at their
    next review: Narrator P0, Network N1, Spatial SP4, SC0, Builder MB0 and
    TITAN P0.

## 10. Build ledger

The Overseer (an owner-directed session working from this index, with no goal
of its own) maintains this section. It records approvals, open goals, gate
verdicts and pending owner actions; the owning plans keep the requirements.
Build sessions do not edit this index. They report gates, blockers and PRs to
the Overseer, which reviews the evidence before recording a verdict. A builder
claim, a driver exit code or green unit tests alone never move a row to PASS.

### 10.1 Baseline and approvals

- B0: `f9b32f0fe0b97f837eeca0966e0fdce794ad144a`. On 2026-11-05 `main` equalled
  `origin/main` with a clean tree. Security Audit and CodeQL passed on that
  SHA. The completed router and combat changes are archived. The only active
  change, `mapping-research-arena-comparison`, is superseded by pilot SP0.
- Owner approvals, 2026-11-05:
  - start the build from B0;
  - worktrees N and S, each with one goal opened from s10.5;
  - SP0 runs inside worktree S under the S goal and merges as a docs PR (this
    replaces the s7 entry that placed it in the main checkout);
  - the Network dev player listener uses port 8370;
  - the remaining Stage 0 docs work (Firelight G0 ADR, pin and gap inventory;
    Pilot P0; pilot schema-review preparation; TITAN s3 seed reconciliation) starts in the
    main checkout after N and S launch.
- An open goal authorizes proposing and building its owning plan's listed
  OpenSpec changes in phase order. Scope beyond the owning plan needs a plan
  review first.
- Standing owner instruction, 2026-11-05: the build proceeds without waiting
  for routine owner approvals. The Overseer merges phase and ledger PRs once
  required CI passes and the evidence supports the gate, and records each as
  "assumed (standing instruction)". It stops for the owner only on IMPORTANT
  items or blockers: ADR acceptance, scope changes to an owning plan, secrets,
  sandbox or installed-campaign operations, outward requests to other
  projects, and human judgement the plans reserve to the owner. Assumed
  approvals never create evidence: no rating, review verdict or live-gate
  observation is invented.
- Stage 1 packet ratings (owner decision 2026-11-05): the owner will not rate
  the 36 Stage 1 packets individually. They are recorded as waived, not as
  ratings. No rating values are entered; Stage 1 stays unrated prompt-only
  evidence and the SP4 report says so. This waiver covers the "(and Stage 1
  packets)" part of S criterion 5. Owner ratings of the SP3 live transcripts
  and M1 sketches are still required (S criterion 5, pilot s7.2); they are
  batched into one owner sitting at SP4.
- Overseer rulings on N0, 2026-11-05:
  - N0's inert transport fixture runs on port 8370. The Capture Arena/8360
    procedure applies from N4, or whenever N drives real gameplay on a
    campaign copy.
  - No sandbox grant for `~/.docker` or `~/.semgrep`. Both hold credentials,
    and Docker socket access would escape the sandbox. The N0 Linux leg runs
    as a reviewed, non-mutating script that the owner executes outside the
    sandbox; N reviews the evidence.
  - CI Semgrep is authoritative. Local runs redirect settings, log and cache
    under `tmp/` with metrics off.
  - Worktrees share the `coding-agent::NeverEndingQuest` Hindsight bank by
    design; this is not a defect.
- Not yet approved: worktrees R, SB, SC, M, T, B and G, and any
  installed-campaign operation.
- Standing authorization for worktree sessions (owner approval 2026-11-06).
  Sessions N and S proceed without relaying routine approvals through the
  owner or the Overseer, keep their goals active, and pause only at the stop
  points below.
  - Pre-approved within an already-approved change or phase: propose, build
    through `openspec-build-loop`, open a PR, wait for CI, rebase on
    `origin/main`, archive a completed change, update the change's own docs,
    and make bounded fixes inside the approved scope. A session may merge its
    own implementation, archive or docs PR only when all required CI checks
    pass, the change's focused verification passes with exact commands
    recorded, and the PR claims no gate verdict. Rebase merges only;
    `--match-head-commit` on every merge; every `gh` command names
    `--repo zeug-zz/NeverEndingQuest-TTRPG`.
  - Live windows: booked mechanically through the shared lock below, without
    an Overseer booking, but only for a live run that a recorded ruling has
    already authorized (N2 gate under the #107 conditions; SP3b only after
    its amendment is frozen).
  - Still stops (pause with the reason in the mailbox): owner ratings and
    audits (SP4 D1 audit, M1 and transcript ratings); ADR acceptance;
    preregistration amendments, including freezing the SP3b amendment;
    any new dependency, package, browser or tool install beyond those
    already named in a ruling; scope changes to an owning plan or approved
    change; secrets, sandbox grants or installed-campaign operations;
    outward requests to other projects; any gate verdict (sessions submit
    evidence, the Overseer records PASS/FAIL); and any failed final attempt
    under a bounded-retry rule.
  - Sessions do not edit this index; the Overseer records verdicts and ledger
    state from the mailbox. Assumed approvals never create evidence.
- Coordination mailbox and live-window lock (owner approval 2026-11-06). The
  shared directory is `<git-common-dir>/neq-coordination/`, resolved with
  `git rev-parse --path-format=absolute --git-common-dir` (currently
  `~/Projects/NeverEndingQuest/.git/neq-coordination/`). It is outside every
  working tree, never committed, and reachable through the existing
  linked-worktree git-dir grant. If a session cannot read or write it, that
  session reports the denial to the owner rather than working around it.
  - `inbox/<N|S>.md`: the session appends a dated UTC entry for each
    report, PR, stop point or evidence submission. Append only.
  - `rulings/<N|S>.md`: the Overseer appends rulings. A session reads it at
    each resume and between tasks; a ruling there has the same authority as
    one pasted into its session.
  - `bookings.log`: append-only record of every acquire, release and stale
    break.

- Owner decisions, 2026-11-10, on the [V2 fable review](v2-fable-review.md)
  decision sheet (s4 there). All twelve were approved as recommended:
  - OD-1 SP4 closes on existing evidence: the D1 claim audit (1,048 rows) is
    recorded as NOT AUDITED, so S criterion 4 is met through its "reported
    blocked with evidence" branch; the 85 percent precision gate is not
    assessed and S3 backfill stays closed; new layouts come only from the
    Builder plus a small hand-authored set (`plans/v2-mapping-pilot.md`
    D1 fallback). The seven rateable SP3 transcripts are owner-WAIVED as
    superseded (a recorded waiver, not ratings; no values are entered). Format
    is decided in the S1b proposal, combat granularity and enforcement at SC0,
    and the data pipeline at S3/MB0.
  - OD-2 worktree R opens after the Narrator P0 gate, not the pilot gate.
  - OD-3 Narrator P0 and Firelight G1 run in the main checkout; G1 uses the
    toolchain and release download named in its ruling; the G0 latency budget
    is ratified before G1 measures.
  - OD-4 worktree G opens after the G1 gate and the shared identity contract,
    with no frozen-configuration study in flight in S.
  - OD-5 new change `test-runner-ci-tier` (fable review FR-10), advisory in CI first.
  - OD-6 live-gate preflight (FR-11): no ruling authorizes a live booking
    without a preflight report showing zero infrastructure failures at the SHA
    to be run; one line is added to `AGENTS.md`.
  - OD-7 `tt-single-runtime-unification` (FR-16) runs now, before the Narrator
    P0 baseline capture, with its own live regression.
  - OD-8 Narrator gates are renamed "Gate P0" to "Gate P6"; P0 is extended per
    FR-12; the P2a/P2b order (FR-33) is approved only after P0 confirms it.
  - OD-9 Spatial S1 splits into S1a and S1b; S2a is added (FR-21, FR-31).
  - OD-10 `v2-context-views` starts with a byte-identical prompt-assembly
    extraction (FR-23); new change for atomic-write remediation (FR-24).
  - OD-11 at most three worktree goals at once (N, S/SB, R); G replaces N when
    N retires; Builder MB0-MB1 held to Wave 4.
  - OD-12 one seeded 1-PC and one four-PC capture session may feed more than
    one track's evidence when each owning plan's requirements are met in full;
    each ledger judges its own rows.
- Concurrency constraint, 2026-11-10 (owner): subscription limits allow only
  TWO goal orchestrator sessions at once for now (N and S). This is stricter
  than OD-11 (three) and governs until the owner lifts it. The Wave 1
  main-checkout goal (fable review FR-11 preflight, FR-10 runner and CI tier,
  FR-16 unification, FR-12 Narrator P0, FR-13 G1, FR-14 Pilot P0 close, in the
  review's order of value) opens in the slot freed by whichever of N or S
  completes first. Worktrees R, SB, G and M then open one at a time as slots
  free, in the gate-keyed order of s7. Work that needs no new session stays
  with the Overseer (docs and ledger).
- Port status, 2026-11-10: the fable review's ledger, order, decision and
  Wave 0 changes are in this index and in the status lines of the owning
  plans. The work-package texts (FR-10 to FR-33) still live in the review and
  are the seed for their OpenSpec proposals; the owning plans (Narrator P0
  extension and P2a/P2b order, Spatial S1a/S1b and S2a, Firelight G2/G3
  notes) are amended when each package is proposed.
- Standing delegation, 2026-11-10: the owner delegated routine decisions to
  the Overseer (in-scope PR merges with green CI, provider-free work, harness
  and test fixes, corrected reruns of approved experiments, model spend inside
  an approved study up to USD 1 per study and USD 5 in total, bookings,
  resumes, next-phase starts after a passed gate). Owner escalation remains
  for security-rule relaxation, production or schema changes outside an
  approved change, ADR acceptance, larger spend, owner-only judgements,
  credentials, destructive actions and outward publication.
- Coordination relay (2026-11-08 onward): campaign `neq-current-build` under
  `<git-common-dir>/overseer-relay/campaigns/` binds N as role A and S as role
  B; framed reports accompany the prose inbox; gated goal resumes are enabled.
  The legacy mailbox remains the prose and rulings channel.
- Owner decision, 2026-11-12: spatial pilot outcome. The mapping pilot is
  closed (SP4 decision gate). Mise-en-scene remains the overall goal for
  spatiality: coherent, narrator-first scene staging of one shared world in the
  theatre of the players' mind. The owner decided from the pilot evidence how
  it is delivered:
  1. Python ingests module source. The LLM Builder authors spatial grids
     together with narrator-facing descriptions, calibrated on the owner's
     examples and the owner-reviewed assistant-authored grids in
     [owner feedback](v2-mapping-pilot-owner-feedback.md) (market AB01,
     tavern AB03, crossroads V01, scarecrow hollow V02 and the appendix
     examples).
  2. The Builder is a creator: it may author module reality
     (`builder_authored`), and it deliberately leaves open facts unknown as
     hooks for TITAN to resolve and evolve at runtime.
  3. That world reality passes back to Python (canonical store) and to
     Firelight (mechanical legality) for gameplay.
  4. The Narrator narrates world facts richly, constrained by Python and
     Firelight; it never resolves an open fact by narration.
  Evidence: SP3 live narration invented space wherever a fact was unknown or
  unauthored (E07, E11, E12, C05, C06); M1 rated authored layouts 5.0/4.6
  against 1.545/2.091 for unguided generated sketches, so generation needs
  exemplars and validation; the LLM staging studies (1, 2, 3, 3b) were safe
  and faithful but extractive, so scene value comes from authored structure
  plus the Narrator, not a standalone LLM staging pass; only that standalone
  pass is closed. The arm comparison itself
  stayed inconclusive. The outcome is consistent with accepted ADR-0034
  (Python spatial authority, provenance classes, open facts resolved only by
  the Builder or TITAN) and ADR-0033 (Firelight legality) and needs no ADR
  change now. It directs the OD-1 deferrals: the data pipeline is
  Builder-authored (legacy S3 backfill stays closed except through the
  Builder), and the map representation is grids plus descriptions. Specifics
  -- grid schema and scale, the exemplar set, validation by machine scoring
  against authored source (no owner row-by-row audits), combat granularity,
  TITAN open-fact interfaces and the Narrator packet shape -- are worked
  through in the owning builds: Builder MB0-MB2, Spatial S1a/S1b, S2/S2a and
  SC0, TITAN, Narrator and Firelight.

### 10.2 Worktrees and goals

| Worktree | Branch | Base | Goal | Current phase | Next gate |
| --- | --- | --- | --- | --- | --- |
| N | per-change feature branches (N3: `feat/n3-*`) | B0 | Opened 2026-11-05 (goal `611274ea`) | N2 PASS and archived (#141-#143, #145); N3 sharing lifecycle (#140, #143, #147, #151, #152) and packaging (#144, #149, #150) merged; N3 live attempt 3 FAIL at L02 (identity initialization, before any companion launch), offline diagnosis authorized | N3 live lifecycle gate (attempt 4) |
| S | final PRs #127, #146, #148 merged | B0 | Closed 2026-11-11 (goal `a9effa87`, unmet: completion criterion 5 discharged only by owner waiver) | Pilot closed; Study 3/3b tooling (#127), FR-04 archive (#146), SP4 closeout (#148) | -- |
| main | per-package branches | -- | Free slot; Wave 1 goal awaits owner creation | -- | FR-11 preflight tool |
| (scratch) | detached `tmp/overseer/main-baseline` at `1a94e364` | -- | none | Overseer scratch checkout for independent verification | -- |

Both worktrees were created 2026-11-05 as siblings of the main checkout:
`~/Projects/neq-v2-network` and `~/Projects/neq-v2-mapping-pilot`. The
nono-sandboxed OpenCode wrapper starts only inside its approved roots:
`~/Projects` and, once the 2026-11-05 wrapper update is installed, OpenCode's
built-in worktree root `~/.local/share/opencode/worktree`, with the main
repository's shared git dir granted for linked worktrees.

Live window: FREE. S released SP3 booking `sp3-s-20261105t200000z` at
`2026-11-06T02:18:55Z` after teardown; the Overseer verified port 8360 free at
`2026-11-06T04:18:56Z`. From 2026-11-06 the window is booked mechanically
through the shared lock; live work on 8360 or 8370 never overlaps.

Live-window lock rules (`C` is the coordination directory above):

1. One holder at a time for ports 8360 and 8370 together. Acquire with
   `mkdir "$C/live-window.lock"`; the atomic `mkdir` either succeeds (the
   session holds the window) or fails (someone else does; do not retry in a
   loop, do other eligible work or pause).
2. Immediately after acquiring, write `"$C/live-window.lock/holder.json"`
   with `booking_id` (`<gate>-<N|S>-<UTC yyyymmddThhmmssZ>`), `holder`,
   `gate`, the authorizing ruling (ledger commit or mailbox entry),
   `window_start`, `window_end` (at most 8 hours later), and the run's
   frozen caps. Append the same line to `bookings.log`.
3. Before launching, confirm no listener on 8360/8370 except one the holder
   starts. The run's own caps and stop rules still apply (SP3b: the
   remaining 287 attempts and the cumulative six-hour cap; N2: its approved
   gate plan). Do not start a row or scenario that cannot finish before
   `window_end`.
4. Release only after teardown and a no-listener check: append a release
   line with the time and evidence path to `bookings.log`, delete
   `holder.json`, then `rmdir` the lock. Report the release in the inbox.
5. Stale lock: if `window_end` passed more than 30 minutes ago and nothing
   listens on 8360/8370, another session may append a `stale-break` line
   citing the old booking, remove the lock and acquire it anew. It reports
   the break in its inbox; it never alters the old holder's evidence.
6. A lock that is missing `holder.json` for more than 10 minutes after
   creation counts as stale under rule 5's no-listener condition.

SP3 collection closeout (run `sp3-s-20261105t200000z`; owner adjudication
pending, not a gate verdict):

- 26 of 30 slots attempted; R01-R04 reserves unused and reported missing.
  Primary row verdicts: 18 FAIL, 8 BLOCKED, 0 PASS; E01 has no finalized
  bundle or score. 513 of 800 attempts and about 57 minutes of the six-hour
  live budget used. Frozen preregistration still verifies 10/10.
- Substantive content failures, all arms: invented destinations for frozen
  unknown doors (E02, E07, E11), an unauthored relocation (E08), extra
  sensory cues beyond authored ones (E12), unsupported distances (C05, C06),
  and stair-to-balcony overshoot (C02-C04, C06, C08).
- Not arm signal: all seven landscape rows (E06, E13-E18) stopped on a host
  `NameError` (`packet_location` undefined in `main_game_loop`,
  `main.py` about line 7486, present on `main` since 2026-03). Six of these
  record no failed rubric check. Combat startup lacked the goblin template
  (C01) and made one unexpected provider call per row (C02-C08); E03-E05 lost
  transport before the first scripted reply.
- Protocol deviations for owner adjudication: the booking forbade changing the
  baseline between arms, but seven tooling-only re-freezes
  (`identity-freeze-*.json`, `scripts/` only) were made during collection;
  repeated same-cause landscape failures did not trigger the three-consecutive
  infrastructure pause.
- S's report marks all five recommendations inconclusive. ADR-0034 remains
  Proposed. SP2 D1 audit, M1 and transcript ratings, and the SP4 owner
  choices remain pending. Tooling PR #97 merged (`5999af37`) after the
  Overseer reran its 241 tests on the exact rebased head.

SP3 owner adjudication (2026-11-06, owner accepted the Overseer
recommendations):

- Main-run verdict: INCONCLUSIVE for every arm comparison. The substantive
  content failures above stand as qualitative findings: no arm prevented
  invented spatial facts. Content-failed rows are never rerun.
- Deviation 1 (seven mid-matrix re-freezes) is accepted as a recorded
  deviation, not waived: changes were limited to `scripts/`, frozen
  preregistration hashes verify 10/10, and every row records its freeze.
  Main-run rows are not pooled across freezes for arm comparison.
- Deviation 2 (missed three-consecutive infrastructure pause) is recorded;
  the affected landscape rows are infrastructure-classified and eligible for
  the supplementary run, not scored as arm content.
- Host defect fixed in PR #105 (`9291994f`): DM Note connectivity fallback
  no longer raises `NameError` for locations without same-area connectivity;
  1-PC and 4-PC regressions added.
- SP3b supplementary run AUTHORIZED in principle, provider budget limited to
  the unspent main-run balance (287 attempts; the six-hour cumulative live cap
  is unchanged and continues from about 57 minutes used). Preconditions:
  S writes a preregistered amendment as a new file beside the frozen
  preregistration (frozen files unchanged, still 10/10), listing exactly the
  infrastructure-classified cells (landscape E06/E13-E18, C01, E03-E05,
  E01 and any combat cells invalidated by the startup provider call), the
  harness fixes for each cause, its row order, and its stop rules including
  an enforced three-consecutive infrastructure pause. The amendment freezes
  one source/dependency/routing identity for the whole SP3b run; any
  mid-run change stops the run. The Overseer reviews and freezes the
  amendment, then books port 8360 separately; no SP3b live work before both.
  Booking superseded by s10.2: after the specific freeze S self-books via the
  live-window lock.
- SP3b amendment ruling (2026-11-06): PR #109 merged (`d2f70d4b`) as
  `plans/v2-mapping-pilot-prereg/SP3b-amendment.md`, SHA-256 `ce49bead...0313`,
  status DRAFT / NOT FROZEN. Overseer verified the 19 source-cell bindings and
  filtered order against `counterbalance.json`, frozen preregistration 10/10,
  and the 287-attempt / 18,146.6-second remaining ceiling. Scope APPROVED
  (E01, E03-E06, E13-E18, C01-C08; C02-C08 as startup-invalidated samples
  whose content findings stand). Implementation of amendment s2 harness
  corrections 1-6 and `scripts/test_mapping_pilot_sp3b_execution.py` is
  AUTHORIZED, provider-free, under s10.1 self-merge rules: no host/core, fixture,
  script, rubric or tripwire changes. Host regression evidence for #105 runs in
  its own process (`PYTHONPATH=. .venv/bin/python -m unittest
  scripts.test_main_location_connectivity_note_fix`, Overseer: 6 OK);
  co-loading it with tripwire-armed suites is a known isolation limitation,
  not a host defect. The freeze is a separate stop point: S submits passing
  test evidence, lifecycle/startup profiles and a draft `execution-freeze.json`
  identity; only a specific Overseer freeze ruling permits booking or live work.
- SP3b lifecycle-profile ruling (2026-11-06T18:55Z): static source reading
  could not establish per-fixture startup/resume provider-call profiles; one
  provider-free stubbed-router profiling attempt was authorized, with a
  pre-declared fallback: rows without a verified profile are BLOCKED, and if
  none can be profiled SP3b closes BLOCKED.
- SP3b CLOSED BLOCKED (2026-11-06, Overseer, applying that fallback): the
  single attempt aborted before any path ran (`ModuleNotFoundError:
  scripts`, an invocation defect) and its harness also stopped after the
  first path; 0 of 8 fixture-party profiles accepted, so all 19 rows
  (SP3B-001..019) lack a verified profile and none may run. Overseer verified
  evidence hashes (`primary-review.json` `31d646f6...1643`,
  `profile-report.json` `75f4e930...02db`). No seeding, server, listener,
  booking, provider call or new gameplay evidence occurred; the 287-attempt /
  18,146.6-second balance is unspent. This is an implementation/coverage
  failure, not proof that profiling is impossible; reopening SP3b requires a
  new owner-level authorization, not a retry. The amendment stays DRAFT / NOT
  FROZEN. Main SP3 remains INCONCLUSIVE with its content findings and
  recorded deviations. SP3b harness/report PR #111 may merge as unexecuted
  research tooling under s10.1.
- SP4 OWNER GATE OPEN on existing evidence: the 1,048-row D1 claim audit,
  16 M1 sketch ratings, 25 SP3 transcript review packets (7 rateable, 18
  not rateable; all scores blank), the format, combat-granularity and
  data-pipeline choices, and the ADR-0034 decision (Proposed). None may be
  imputed. With no arm comparison available, ADR-0034 should be expected to
  need revision rather than acceptance as drafted.
- Owner M1 review completed (2026-11-07): all 16 original sketches rated;
  legibility/usefulness means 2.625/2.875, below 3.5 on both axes. Both combat
  fixtures scored 5/5; all five authored fixtures averaged 5.0/4.6, compared
  with 1.545/2.091 for the eleven D1-generated sketches. These descriptive
  groups explain the quality contrast but do not replace the aggregate gate.
  [Owner feedback and nine expanded examples](v2-mapping-pilot-owner-feedback.md)
  preserve all original scores, corrections, redesigns and separate assessor
  judgments. The M1 sheet is no longer blank; D1 and transcript inputs remain
  pending.
- Owner directs that mise-en-scene lessons be embedded going forward:
  narrator-first coherent scene authoring and canonical relationships, player
  maps derived afterward. S is AUTHORIZED to resume provider-free planning:
  append the completed M1 evidence to its report and propose a new prospective
  authoring/projection/evaluation change with cross-track handoffs. Use the
  worked examples, Python topology, source/authoring provenance, knowledge
  boundaries and held-out evaluation criteria. Submit for Overseer review
  before implementation. This does not reopen SP3b, alter frozen pilot
  artifacts or scores, authorize live spending or production seeding, open
  later worktrees, complete SP4, or accept ADR-0034.
- 2026-11-09: owner reviewed the revised ADR-0034 (PR #119, merged
  `01e710ee`, including the "Open facts and TITAN resolution" section) and
  ACCEPTED it. Acceptance permits S1 and later spatial phases to be proposed as
  their own OpenSpec changes; it does not authorize implementation, select a
  format or combat enforcement level, or approve evaluation budgets. Still
  pending owner inputs: D1 audit (1,048 claims), seven transcript ratings,
  format, combat granularity/enforcement, backfill-versus-Builder data
  pipeline, and any Section 2 live evaluation. Offline mise-en-scene prototype
  (PR #116), holdout draft (PR #118/#123, unfrozen) and staging-study protocol
  (PR #120/#127, 3-call study pending transport review) are in progress.

N2 proposal rulings (2026-11-06; change `v2-react-player-vertical-slice`,
draft PR #103; N1 archived in #102 at `77bb3f1a`). Approved under the
standing owner instruction:

1. Route layout: serve the shell at the existing player `GET /` and assets
   at `GET /static/player/<asset-id>`, not plan s6's `/client`. This keeps
   the N1 allowlist unchanged; any later new route or event first needs a
   MODIFIED `player-capabilities` requirement and inventory-test update.
2. `NEQ_PLAYER_DEV_LISTENER=1`: off by default, loopback `127.0.0.1:8370`
   only, no bind/port override, existing scrypt verifier required, host
   play unaffected on failure, every host edit marked `# TABLETOP MODE:`.
   Temporary; N3 sharing controls replace it.
3. Frontend dependencies: the ten named packages only (`playwright`
   dev-only). Exact current stable versions, committed lockfile, install
   with `npm ci` inside `web/frontend/` only. Before merge, the
   implementation PR must carry the direct/transitive license inventory
   and a clean `npm audit --audit-level=low`; any copyleft, unknown or
   unlicensed package, or an added package, returns for review. The Node
   setup action is pinned to a commit SHA whose provenance is recorded in
   the PR.
4. Generated `web/frontend/dist/` and `node_modules/` stay gitignored in
   N2; prebuilt distribution belongs to N3.
5. Browser evidence: installing Playwright Firefox and WebKit binaries
   into the user's Playwright cache is authorized, using the lockfile's
   pinned `playwright` version, after task 2.1 and with no other system
   changes. A sandbox denial is reported, not worked around. The external
   owner-run driver path requires separate review before use. With no real
   browser path the gate is BLOCKED; socket-only evidence never passes it.
   The live gate (host 8360, player 8370, isolated Capture_Arena) needs its
   own booking and is serialized with S's SP3b.

### 10.3 Gate record

| Gate | Worktree | Verdict | Date | Evidence | PR |
| --- | --- | --- | --- | --- | --- |
| N0 transport feasibility | N | PASS | 2026-11-05 | `openspec/changes/v2-network-transport-feasibility/n0-verdict.md`; independently reviewed macOS 22/22 and Linux arm64-container 23/23; teardowns verified; 12 fixture tests and 63 driver self-test PASS entries (0 FAIL); strict validation; required CI and CodeQL pass; advisory Semgrep findings reviewed, not suppressed; assumed (standing instruction) | #89 (`62e9ec17` integrated head) |
| N1 player boundary and contract | N | PASS | 2026-11-06 | Initial head `196fd98d` held after the Overseer reproduced a stale active-PC revision rollback; one bounded correction plus verification-only continuation; Overseer independently re-verified the final head `a7abddcd`: focused N1 99 OK, rollback reproducer and lifecycle probes 0 failures (1-PC/4-PC), host/combat suites 75/26/13/13/7/15 OK, ASCII/Bandit/Semgrep clean, CI 10/10. Pre-existing request-path gaps surfaced by CodeQL fixed separately in #98/#99; remaining character-name alerts dismissed as false positive with owner approval (private review `plans/security/pr93-n1-review.md`). N2 requires separate authorization | #93 (`0b12f44f` integrated head) |
| N2 React vertical slice | N | PASS (Chrome and Firefox; 1-PC and 4-PC) | 2026-11-11 | P1 `tmp/router-rollout/v2-network/n2-firefox/p1-ff2-20261111T023456Z` and P4 `tmp/router-rollout/v2-network/n2-firefox/p4-ff-20261111T023550Z` (N worktree), each 11/11 PASS; the Firefox test client ran with its own content sandbox disabled inside nono (test environment only); change archived | #141, #142, #143, #145 |
| N3 tunnel, installers, sharing UX | N | in progress: live attempts 1-2 BLOCKED (harness), attempt 3 FAIL at L02 with no relay contact | 2026-11-11 | `tmp/router-rollout/v2-network/n3/n3-20261111-175359/` (N worktree) | #140, #144, #147, #149, #150, #151, #152 |
| N4 internet gameplay and release | N | pending | -- | -- | -- |
| SP0 preregistration reviewed | S | PASS | 2026-11-05 | `plans/v2-mapping-pilot-prereg/` (MANIFEST.sha256 verified 10/10); owner reviewed and approved | #81 (`c6ed675b`) |
| SP1 tooling | S | PASS | 2026-11-05 | Overseer reviewed exact PR head; 16/16 tasks, strict change validation, frozen hashes 10/10; post-merge provider-free suite 133/133 PASS (`tmp/overseer/pr87-postmerge-tests.log`); research-only changed-path boundary verified; assumed (standing instruction) | #87 (`c11bd385` integrated head) |
| SP2 offline D1/M1 | S | M1 below threshold; D1 NOT AUDITED (OD-1) | 2026-11-07 | Original M1 16/16 owner-rated: 2.625 legibility / 2.875 usefulness, below 3.5. Combat fixtures 5/5; redesign ratings excluded. D1 20 attempts (11 validated, 9 invalid layouts); 1,048 claim rows unaudited. See owner feedback for exact scores and next planning direction | #94 (`e40e4899`) |
| SP3 live matrix | S | INCONCLUSIVE (main run); SP3b BLOCKED (no verified lifecycle profiles) | 2026-11-06 | 26/30 slots attempted, 18 FAIL / 8 BLOCKED / 0 PASS; content failures stand as qualitative findings; landscape host NameError fixed in #105; re-freeze and missed-pause deviations recorded, not waived. Not a PASS | #97 (`5999af37`), #105 (`9291994f`) |
| SP4 decision gate | S | CLOSED; owner-decided outcome recorded 2026-11-12 (s10.1) | 2026-11-12 | `openspec/changes/v2-mapping-pilot-execution/reports/sp4-primary-report.md`; D1 not audited and transcripts waived (OD-1); completion criterion 5 by owner waiver | #148 |
| Mise-en-scene LLM staging studies | S | CLOSED as a standalone LLM staging pass (mise-en-scene remains the spatial goal): studies 1-2 FAIL (protocol defects); study 3 FAIL as run (1 model-attributable guarded leak, 2 harness parity); study 3b 2/3 deterministic PASS, Overseer semantic review safe and faithful but extractive (low staging value); no Study 4 | 2026-11-12 | `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/` (S worktree); total spend about USD 0.047 | #127 |
| Narrator P0 contracts (extended, FR-12) | main | pending (approved OD-3/OD-8) | -- | -- | -- |
| Firelight G1 offline spike | main | pending (approved OD-3; budget ratification first) | -- | -- | -- |
| G0 ADR, audit and pin (docs) | main | PASS | 2026-11-05 | ADR-0033 accepted by the owner; `plans/v2-firelight-g0/gap-inventory.md`, `design.md`; release `SHA256SUMS` matches `gh release download v0.1.0` | #83 |
| Memory Pilot P0 contracts | main | pending | 2026-11-05 | `plans/v2-memory-pilot-p0/baseline-audit.md`; audit ready, premature production request withdrawn; fixture/rubric and budget contracts still pending | #84 (audit); scope correction follows |

Verdicts are PASS, FAIL or BLOCKED, each with an evidence path. Pending means
not yet judged.

#### SP4 handoff to the Module Builder

Owner-directed report clarification: SP4 includes an explicit module-data
requirements and gap list drawn from D1 and the pilot representation decision.
This makes the existing S1/S2/SC1/S3/S4 handoff actionable for Builder MB0's
next contract review; it does not authorize Builder implementation in S.

For each required spatial fact/field, the report records:

- The consuming projection/behavior and why the fact matters to players.
- The proposed field, units and schematic-versus-metric meaning; unknown or
  not-applicable values stay explicit. No exhaustive grid requirement is
  assumed before the representation decision.
- Authored presence and missing/ambiguous counts with denominators for the
  D1 sample (about 20 locations across three modules), identifying the sampled
  module/location versions. Findings are sample coverage, not corpus-wide
  prevalence. Fields outside D1's scope are marked not assessed.
- Whether the value is already authored, safely derived by a stated rule,
  requires new authoring, or remains unknown. LLM cartographer proposals are
  labelled proposals with audit results, not promoted to source facts.
- Ownership and follow-up: Spatial S1 schema/query contract, Builder MB1/MB2
  generation requirements, and S3 backfill feasibility. Preserve the existing
  D1 precision/zero-invented-exits gate; backfill does not become authorized
  merely because a field is missing.

The Builder review consumes this list and defines any generation, migration
or backfill changes through separately approved OpenSpec work. Builder-side
generation tests and the applicable Spatial live gates must establish that
generated data works in play; S research alone cannot prove that.

This is a synthesis of existing D1/SP4 evidence, not a new experiment. The
frozen preregistration, budgets, matrix and scoring thresholds are unchanged;
no extra calls, module census, production edits or fabricated measurements
are authorized. Missing evidence is reported explicitly.

### 10.4 Pending owner actions

All decision-sheet items OD-1 to OD-12 were answered 2026-11-10 (s10.1). Open:

1. Open the Wave 1 main-checkout goal in the free slot (goals are created
   only at the owner's request).
2. LuLu outbound allow rule for the capture-copy companion
   (`~/Projects/neq-v2-network/tmp/combat_capture/runtime/opentunnel/v0.6.2/opentunnel-darwin-arm64/opentunnel`)
   before the next N3 live attempt; the N3 Linux leg remains owner-run.
3. Repository variable `PLAYER_BUNDLE_PUBLISHERS` before the first tester
   release tag.
4. NEQ-world production seed job: awaits sign-off of the 240-fragment pilot
   schema.
5. Making the `test-runner-ci-tier` check required after ten green runs
   (branch protection is an owner action).

N0 closeout: the owner-run Linux leg completed and both tunnels are down.
The guarded identity bootstrap (`up` -> `status` -> `down` with isolated
paths and service-manager commands unavailable, then foreground `serve`)
is approved for the spike; production startup/packaging remains N3-owned.
N0 proves macOS arm64 and Linux arm64-container transport feasibility, not
native Linux installation, x64 qualification, browser or gameplay acceptance.
No Docker/Semgrep sandbox grant or speculative listener-profile edit is
required for this completed gate.

Owner correction, 2026-11-05: the earlier full-public-seed request was
premature and is withdrawn; its unmodified local copy in NEQ-world was
deleted with owner approval. The consumer checklist remains a deferred
reference (`plans/v2-memory-pilot-p0/producer-request.md`), not a live request.
First evaluate the delivered 240 fragments with TITAN/Builder scenarios,
iterate and sign off the optimized schema, then separately authorize the
large production job. P6 remains a later release gate.

Done 2026-11-05: ADR-0033 (Firelight) accepted, with its `AGENTS.md` rule.
N and S sessions opened with their s10.5 goals; `config.py`
provided in both worktrees; SP0 preregistration reviewed, approved and merged
(#81), which freezes it and clears the pilot for provider calls under its
protocol. The superseded `mapping-research-arena-comparison` change is
archived, so `main` has no active OpenSpec change. The superseded
mapping-research goal is closed. The updated nono wrapper is installed.
Stage 1 packet ratings waived (s10.1).

### 10.5 Goal prompts

Superseded phrases (do not edit open goal prompts): "merged by the owner" and
"booked with the Overseer" were superseded by the 2026-11-06 standing
authorization and the 2026-11-10 delegation (s10.1); "per-worktree Hindsight
namespace" was superseded by the shared bank ruling (s10.1, N0 rulings).

Paste each prompt as the `/goal` in its worktree session, unchanged. The
operating rules are shared; the S objective and criteria are copied verbatim
from `plans/v2-mapping-pilot.md` s11.

**Worktree S** (`feature/v2-mapping-pilot`):

```text
Worktree S, branch feature/v2-mapping-pilot, base f9b32f0f. Authority:
plans/v2-mapping-pilot.md; program index plans/v2-narrative-overview.md (s10
ledger, owned by the Overseer). Operating rules: research only, in scripts/,
sandbox fixtures and tmp/; no production default changed and no core hook
without explicit owner approval (pilot plan s5.3). SP0 is phase 1 of this goal
and merges as a docs-only PR; no provider call before the owner has reviewed
it. One OpenSpec change per phase as listed in pilot plan s9, proposed with
openspec-propose and built with openspec-build-loop; one small PR per phase to
origin main, merged by the owner; rebase onto main after each merge. Live
captures only through neq-capture-arena on port 8360, booked with the Overseer
and never overlapping Network live work; never port 8357 or the installed
campaign. Own .venv; owner-provided config.py; per-worktree Hindsight
namespace. Do not edit plans/v2-narrative-overview.md; report each gate,
blocker and PR to the Overseer. Do not touch MULTIPLAYER_MODE or party-size
gates.

Objective: Determine, through preregistered live Capture Arena play with
one-PC and four-PC parties, which spatial context best improves gameplay UX in
the theatre of the players' mind. Compare the current game with
explicit-relationship and hybrid spatial packets, test a theatre-of-the-mind
zone ledger for combat, and assess layout backfill feasibility and shared map
sketches. Deliver an evidence-backed decision report, a draft spatial ADR and
concrete inputs for the v2 spatial build, without changing production
behavior.

Immutable completion criteria:
1. SP0 preregistration (fixtures, scripts, rubric anchors, thresholds,
   budgets, frozen route) is reviewed before any provider call. The superseded
   change is archived with a pointer.
2. Tooling has passing provider-free tests and ASCII compliance, proves arm A
   is a no-op, and changes no production default.
3. The s6 matrix is executed within caps. Every cell is reported PASS, FAIL,
   BLOCKED or missing with preserved evidence. Nothing is silently waived.
4. D1 and M1 are completed and owner-audited, or reported blocked with
   evidence.
5. Owner ratings exist for the live transcripts (and Stage 1 packets). No
   ratings are invented.
6. The decision report, draft ADR and S1/S2/SC1/S3/S4 inputs are reviewed at
   the owner decision gate.

The goal may close unmet only with a concrete blocker and evidence. An
*inconclusive* verdict with complete evidence satisfies criteria 3 and 6.
```

Correction, 2026-11-05: both prompts say "per-worktree Hindsight namespace".
The prompts are kept as pasted, but that clause is superseded: worktrees share
the main repo's Hindsight bank by design (s10.1 rulings).

**Worktree N** (`feature/v2-network`). The criteria restate the plan's s9 gates
and s11 checklist; the plan wins on any difference.

```text
Worktree N, branch feature/v2-network, base f9b32f0f. Authority:
plans/v2-server-client-network.md; program index plans/v2-narrative-overview.md
(s10 ledger, owned by the Overseer). Operating rules: Python stays
authoritative for mechanics, narration orchestration, validation, combat,
party state, persistence, publication and campaign state; React owns
presentation and local UI state only. Do not touch MULTIPLAYER_MODE or
party-size gates. Core host edits are marked # TABLETOP MODE:; prefer
extensions. Dev player listener on port 8370; never use port 8357 or the
installed campaign as a fixture. Live gates only through neq-capture-arena on
port 8360, booked with the Overseer and never overlapping pilot live work.
One OpenSpec change per network plan s10 entry, proposed with openspec-propose
and built with openspec-build-loop; one small PR per phase to origin main,
merged by the owner; rebase onto main after each merge. Own .venv;
owner-provided config.py; per-worktree Hindsight namespace. Do not edit
plans/v2-narrative-overview.md; report each gate, blocker and PR to the
Overseer. Material architecture or scope changes found in N0 go to owner plan
review before code.

Objective: Deliver Network N0-N4 of plans/v2-server-client-network.md, so that
invited internet test players join real NeverEndingQuest gameplay on thin
React browser clients through a facilitator-started OpenTunnel share from a
macOS or Linux host, with every player in the same authoritative Python
tabletop session, from a tagged main SHA.

Completion criteria:
1. N0: macOS and Linux transport feasibility is evidenced with an inert
   authenticated fixture, and the listener, serving stack and tunnel choices
   are recorded. No real campaign or unfiltered host surface is publicly
   exposed. A BLOCKED N0 goes to owner plan review, never a workaround.
2. N1: unauthenticated and authenticated negative tests show that players
   cannot invoke host operations or receive privileged payloads; 1-PC and
   4-PC projections and input validation pass.
3. N2: isolated multi-browser checks show coherent host and player state for
   1-PC and 4-PC parties, no duplicate actions on retry or reconnect, no
   stale-PC misapplication, and no host-only bundle or event leakage. The
   local host works with sharing disabled or with a missing or broken client
   build.
4. N3: clean macOS and Linux installs and updates start local play, start and
   stop authenticated remote play, survive relay loss and restart, and leave
   no unintended live exposure; existing campaigns and unrelated tunnels stay
   intact.
5. N4: the orchestrator runs and judges all eight required live scenarios of
   network plan s9 Phase 4 through the public tunnel URL from a genuinely
   external network, including current Windows Chrome and Edge clients, with
   evidence and the runtime model/provider recorded under
   tmp/router-rollout/v2-network/<run-id>/.
6. Every network plan s11 test category has exact commands and results;
   ASCII compliance, openspec validate --specs and each change's --strict
   validation pass; the security scans run without bypass.
7. Tester documentation (facilitator quickstart, join and reconnect guide,
   platform matrix, network and privacy limits, failure recovery, private
   issue reporting) and a release evidence index with the tagged build
   identity are delivered.

The goal may close unmet only with a concrete blocker and evidence. Missing
platforms, connectivity, credentials, scenarios or assertions are BLOCKED or
FAIL, never waived. Driver exit codes, builder claims and green unit tests
alone do not pass a gate.
```
