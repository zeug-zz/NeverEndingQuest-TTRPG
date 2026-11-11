# V2 Spatial: A Shared World in the Theatre of the Players' Mind

Status: Master plan; each phase still needs its own approved OpenSpec change.
The mapping pilot gate closed on 2026-11-12 with the owner-decided outcome in
[V2 narrative overview](v2-narrative-overview.md) s10.1: Builder-authored grids
plus descriptions, Python and Firelight authority, and the Narrator constrained
by them. Mise-en-scene remains the overall spatial goal. Items marked *[pilot]*
are resolved by that outcome; their specifics are settled in the owning phases.
Date: 2026-11-03.
Track: F (Spatial). Program index: [V2 narrative overview](v2-narrative-overview.md).
Supersedes as planning input: the drafts in `plans/version-2/mapping/` (s13).

## 1. Overriding goal: the theatre of the players' mind

The v2 upgrade as a whole is optimized for **gameplay UX in the theatre of the
players' mind**. Spatiality is where that goal is currently weakest. Players do
not reliably share a picture of where they are, what surrounds them, where they
can go, or where everyone stands in a fight. This track exists to give every
player, local or remote, one coherent, persistent, imaginable world.

Design consequences:

1. **The imagined scene is the product.** Python's spatial model and the LLM
   packets are scaffolding for vivid, consistent narration. They are never shown
   to players as coordinates, grids or rule readouts unless a player asks.
2. **Close enough is good enough.** Python enforces what players notice and rely
   on:
   - reach and engagement;
   - cover and line of sight;
   - routes and blocked paths;
   - committed changes to the world.

   Everything finer, such as exact feet, diagonal geometry or facing, stays
   narrative and approximate, in the theatre-of-the-mind tradition. The
   pilot measures where that line sits.
3. **Stable stage, living actors.** Places, landmarks and exits stay put across
   turns, sessions and return journeys. Changed features stay changed. People
   and creatures move within that stage.
4. **Knowledge-true.** The Narrator and every player view see only what the
   party perceives or knows. A hidden passage, an unexplored room or an unseen
   enemy is not leaked by a map or by narration.
5. **Shared, not prescribed.** The player map is a shared sketch of what the
   party knows, like a DM's sketch pushed across the table. It supports
   imagination and collaboration; it does not replace narration.

This is the spatial face of the Narrator's "sentient ghost in the machine"
(`plans/v2-narrator.md` s1). An attentive DM remembers where things are, as well
as who people are and what happened.

## 2. Authority and scope

Owner M1 review follow-up: [mise-en-scene feedback and worked examples](v2-mapping-pilot-owner-feedback.md)
are required planning input for S1-S4, spatial combat and later regional
design. Prioritize LLM spatial continuity; derive the player sketch from the
same canonical relationships. Explicitly address scene scope, multi-cell
paths/boundaries, initial occupants versus fixed anchors, reciprocal scene
connections and knowledge-filtered cues. This is prospective design input,
not evidence that a format won the live pilot or permission to start S5 early.

- Precedence: `AGENTS.md` > accepted ADRs > active OpenSpec changes > master
  plans > the index. This plan proposes changes and goals; it authorizes none.
- **ADR:** "Spatial authority and projections" is ADR-0034, accepted
  2026-11-09 (`adrs/0034-spatial-authority-and-projections.md`). It records:
  - Python spatial authority;
  - one projection per audience;
  - schematic versus metric coordinates;
  - observed versus enforced legality;
  - the "close enough" rule.
- Python owns topology, layouts, positions, connectivity, legality and committed
  spatial change. LLMs narrate, interpret player intent into proposals and
  author build-time layouts for review. They never commit space by assertion.
- Canonical owners are unchanged. Character JSON, `party_tracker.json`, encounter
  files and module areas stay authoritative. Spatial overlay state is a new
  campaign-scoped record behind a canonical API, written with `safe_write_json` or
  the Narrator P2 store. It is never written as ad hoc JSON or direct SQL.
- Shared paths keep one-PC and four-PC regression checks. No party-size gates.

## 3. Starting point

Audited in [V2 mapping pilot](v2-mapping-pilot.md) s3. In short:

- the Narrator sees only adjacent-location names;
- the full atlas is injected every turn;
- graph IDs can collide across modules, and loading the graph writes repairs;
- `tactical_grid` is a template, and published modules have no
  `tacticalFeatures`;
- combat has no positions;
- there is no player map.

Stage 1 showed that missing facts, not format, drive most spatial failure.

## 4. Design principles

| Principle | Rule |
| --- | --- |
| Projections per audience | One spatial truth, scoped views: Narrator packet, combat packet, actor (enemy/ally) view, player map. Views agree on shared facts, not on payload. |
| Connection, perception, knowledge, traversal | Kept as separate states. Hidden, perceived, known, visible-but-unreachable and blocked are distinct. Absence from a packet never means nonexistence. |
| Schematic versus metric | Display positions are labelled schematic. Distances and travel times come only from authored or derived metric data, or are reported unknown. Independently generated areas never share an implied coordinate frame. |
| Bounded context, no amnesia | Always: current scene, anchors, perceived exits, recent movement. Compact: area/region orientation. On demand: routes and distant places through a Python query. |
| Stage and actors | Environment features (with IDs and properties: obstruction, sight, cover, hazard) are separate from occupants. Coarse summaries orient; Python answers legality. |
| Persistence by overlay | Campaign changes overlay the reusable module. A destroyed door stays destroyed after combat, transitions and save/restore. |
| Regions are not modules | Places and routes are separate from adventure placements. Revealed geography is committed before it is narrated. |
| Validate, commit, then narrate | Movement and spatial change follow proposal -> Python validation -> commit -> narration. An invalid move has no effect; narration never grants movement retroactively. |

## 5. Architecture

```text
Authored module data (areas, maps, scene layouts)  +  campaign overlay
                     + encounter spatial state
                              |
                 SpatialService (Python, read-only queries)
        identity | topology | layout | perception/knowledge | routes
                              |
     +-----------------+------+-----------+------------------+
     |                 |                  |                  |
Narrator packet   Combat packet     Actor view         Player map
(S2, scene)       (SC3, zones)      (SC2, enemy/ally)  (S4, knowledge-filtered)
```

| Layer | Questions | Representation |
| --- | --- | --- |
| Regional (S5) | What lies beyond? How do we get there, and how long does it take? | Places, routes, landmarks, travel costs; rumoured, discovered and visited states |
| Exploration (S1-S4) | Where are we? What connects? What can we perceive? | Location graph plus scene layout: anchors, exit sides, sightlines, elevation |
| Tactical (SC1-SC4) | Can this actor reach, see, affect or take cover from that one? | Zone ledger with bands *[pilot: granularity and enforcement level]* |

Tactical zones derive from the same scene layout as exploration anchors. The bar
the Narrator describes is the cover the combat engine applies.

## 6. Exploration and Narrator phases (S1-S5)

### S1 Spatial foundation

- **Scope:**
  - Module-qualified stable location and feature IDs, with aliases for legacy
    bare IDs.
  - A read-only graph loader. Today's load-time repair writes move into explicit,
    previewable remediation.
  - The `SpatialService` query API.
  - An authored **scene layout schema** *[pilot: SP4 draft]*: anchors, features
    with properties, exit sides, sightlines, elevation and zone hints. It
    replaces the template `tactical_grid`.
  - A campaign spatial overlay (feature state, discovered/visited, known exits).
  - Movement, discovery and feature changes as committed events.
- **Depends on:** pilot gate and spatial ADR. Event wiring waits for Narrator P1
  (committed event envelope). Overlay persistence joins the Narrator P2 save
  manifest; before P2, use a canonical JSON writer that P2 then adopts.
- **Reconciles:**
  - `tt-spatial-coordinate-resolution`: the 9-cell `tactical_grid` requirement
    becomes optional legacy; scene layout supersedes it.
  - `spatial-grid-embedding-solver`: embeddings are labelled schematic.
  - `module-runtime-location-reachability-validation`.
- **Exit:**
  - collision-safe IDs across all published modules;
  - loading writes nothing;
  - overlay round-trips through save/restore;
  - 1-PC and 4-PC regression;
  - module validators pass.

### S2 Narrator spatial packet

- **Scope:**
  - Replace the names-only exits block in the DM note with the bounded spatial
    packet *[pilot: B or D format, caps]*.
  - Reduce the per-turn full atlas to a compact orientation summary.
  - Add a `querySpatial` lookup for routes and distant places, which Python
    answers.
  - Keep packets consistent across normal calls, retries, transitions and
    arrivals.
  - Carry the theatre-of-the-mind instruction: use landmarks naturally; never
    recite the map.
- **Depends on:** S1. Coordinates with Narrator P3/P4: the packet is a
  current-state input to the P4 layered assembler, in its fresh-end region.
  S2 owns the `main.py` exits block and the `core/ai/conversation_utils.py`
  atlas injection first; the Narrator worktree rebases onto it.
- **Exit:**
  - live 1-PC and 4-PC gates repeat the pilot's E1-E4 on real modules with
    S1 data;
  - contradiction and rubric improvements hold against the pilot thresholds;
  - token and latency within the S2 budget.

### S3 Authored spatial data

- **Scope:** Scene layouts for published modules, through one of two routes
  *[pilot: D1]*:
  - **Backfill:** a cartographer pass with human review, as remediation that
    follows the publication Git contract.
  - **Builder-only:** layouts come only from the Builder for new modules, plus a
    hand-authored set for priority modules.

  Either way, Builder MB1/MB2 generate and validate layouts and route data for
  new modules, and `tacticalFeatures` are derived from layout features.
- **Depends on:** S1 schema; Builder MB1/MB2 for new-module generation.
- **Exit:** every published module has layouts or a recorded fallback, and
  validators pass. Backfilled modules are republished through the module Git
  contract.

### S4 Shared player map

- **Scope:**
  - A knowledge-filtered player map projection.
  - An ASCII renderer in the React `/client` and a host tab.
  - Updates on movement, discovery and feature change.
  - A schematic look, labelled as such, with no hidden information.
- **Depends on:** S2. Network N2: the projection is a message type within the
  Network N1 player-projection protocol; `web/` and `/client` changes start only
  after N2 merges. *[pilot: M1 conventions]*
- **Exit:** tester-cohort sessions rate legibility and plan-discussion
  usefulness; there are no leaks in knowledge-filter tests; reconnect resyncs the
  map.

### S5 Regional layer (outline; built later)

- **Scope:**
  - Places and routes, kept separate from module placements.
  - Rumoured, discovered and visited states; travel time and route hazards.
  - Destinations committed before narration.
  - A compact regional orientation line in the packet.
- **Depends on:** S4 and SC2 stable; TITAN P0 contracts. TITAN consumes geography
  for fronts, weather and news; Builder MB3 consumes it for campaign placement.
  This plan does not choose the procedural placement policy, the "no suitable
  module" outcome or world-generation rules. A separate regional plan does,
  before S5 starts.

## 7. Spatial combat phases (SC0-SC4)

The combat refactor made enemy and ally decisions deterministic Python. Spatial
combat is therefore mainly a **Python rules build**. The LLM's new duties are
small: narrate positions coherently, and translate a player's movement intent
into a proposal that Python validates.

### SC0 Contracts

- **Scope:** Accept the spatial ADR's tactical sections. Reconcile:
  - `combat-tactical-cover`: today runtime SHALL NOT infer cover from grid
    cells or positions; that changes to "cover derives from validated layout
    features and the zone ledger";
  - `combat-turn-receipt-model`: the `position_deltas` slot becomes typed;
  - `combat-tactical-brain`;
  - ally controller contracts.

  Set the combat latency budget for any intent call. Decide zone granularity and
  the enforcement level *[pilot: K1-K3]*.
- **Depends on:** pilot gate, S1 schema draft.

### SC1 Encounter spatial state

- **Scope:**
  - Zone ledger built from the S1 scene layout (zones, adjacency, elevation,
    cover, bands).
  - Python placement at initiative.
  - SRD 5.2.1 rules at zone granularity: movement allowance between zones,
    disengage and opportunity attacks, reach (engaged), range bands, cover from
    features, line of sight.
  - Typed `position_deltas` in receipts and the committed encounter snapshot.
  - Enforcement at the level the pilot chose: validate before narration where
    players would notice.
- **Depends on:** SC0, S1.
- **Exit:** deterministic rule tests; receipts round-trip; enemy AC and existing
  cover behavior preserved; 1-PC and 4-PC encounters.

### SC2 Spatial tactical brain and allies

- **Scope:** Deterministic enemy and ally choices use zones, real cover and
  bands (advance, hold cover, flank, focus the reachable). The actor view
  carries only what that actor could know.
- **Depends on:** SC1.

### SC3 Player intent and combat packet

- **Scope:**
  - Free-text movement becomes a validated move proposal; ambiguity triggers a
    short clarification rather than a guess.
  - A per-PC relative view during PC turns, and a roster with environment during
    the enemy phase *[pilot: format]*.
  - Environment changes (a door barred, a table overturned, a fire started)
    go through validated operations and persist into the S1 overlay after
    combat.
- **Depends on:** SC1, S2.

### SC4 Combat map and live gates

- **Scope:**
  - Zone map in the client and host (on top of S4).
  - Live gates for 1-PC and 4-PC.
  - Reruns of the affected archived combat gates (G-series) as regression.
- **Depends on:** SC2, SC3, S4.
- **Exit:** owner and tester rubric for combat clarity and flow; contradiction
  rate within the SC0 budget; no regression in mechanics or turn latency budget.

## 8. Cross-track integration

| Track | Spatial touchpoint |
| --- | --- |
| Network (A) | S4 map projection is a protocol message under Network N1 ownership; client panel after N2; testers rate the map in follow-up cohorts |
| Narrator (B) | S1 movement/discovery events use the P1 envelope; overlay joins the P2 save manifest and generation fencing; S2 packet is a P4 current-state region; P3 retrieval may recall "what happened here" keyed by stable location IDs |
| Memory pilot (C) | Location seed fragments (`location_scene`) may enrich layouts at build time only; no runtime truth |
| TITAN (D) | Consumes the spatial query API and S5 geography; interventions that change places use typed operations validated by `SpatialService`; never bypasses movement, connectivity or tactical legality |
| Builder (E) | MB1/MB2 produce scene layouts, route data and feature IDs to the S1 schema; MB3 binds campaign overlays and module placements |
| Combat baseline | SC phases extend the refactored receipts, tactical brain and ally controller; reruns of affected gates |

## 9. OpenSpec outline (candidate names)

| Phase | Candidate change |
| --- | --- |
| SP0-SP4 | `v2-mapping-pilot-tooling`, `v2-mapping-pilot-execution` (see pilot plan) |
| S1 | `spatial-foundation-identity-and-service`, `spatial-scene-layout-and-overlay` |
| S2 | `narrator-spatial-packet` |
| S3 | `spatial-layout-authoring-and-backfill` |
| S4 | `player-map-projection` |
| SC0-SC1 | `combat-spatial-contracts`, `combat-zone-ledger` |
| SC2-SC3 | `combat-spatial-tactics`, `combat-movement-intent` |
| SC4 | `combat-map-and-live-gates` |
| S5 | Separate regional plan first |

Each change states scope, non-goals, numeric budgets, failure and rollback
behavior, 1-PC and 4-PC verification, and live-gate requirements. Phase order
may be refined with evidence. Criteria are not weakened to hide a dependency.

## 10. Verification and live gates

- Focused provider-free tests per change; module validators; ASCII compliance.
- **Knowledge-filter tests on every projection:** no hidden exits, unexplored
  contents or unseen enemies.
- Persistence tests across leave/return, transition, combat end, save/restore
  and campaign switch.
- Orchestrator-owned live gates (Capture Arena, port 8360, isolated copy) for
  S2, S4 and SC4, with 1-PC and 4-PC parties. Evidence goes under
  `tmp/router-rollout/spatial/<gate>/<run-id>/`.
- The theatre-of-the-mind rubric (pilot s7.1) is the UX acceptance measure at
  S2, S4 and SC4. Tester cohorts supplement owner ratings once Network N4 has
  shipped.

## 11. Candidate goals

| Worktree | Objective basis | When |
| --- | --- | --- |
| S `feature/v2-mapping-pilot` | `plans/v2-mapping-pilot.md` s11, verbatim | After B0 and owner approval |
| SB `feature/v2-spatial` | Deliver S1-S4 so players share one coherent, persistent, knowledge-true imagined world, with live 1-PC and 4-PC gates at S2 and S4 | After the pilot gate; may reuse the S worktree after the pilot branch merges |
| SC `feature/v2-spatial-combat` | Deliver SC0-SC4 theatre-of-the-mind zone combat with Python-validated movement, reach, cover and sight, and live gates | After S1 merges and SC0 is accepted |

S5 gets its own plan and goal later.

## 12. Non-goals and deferrals

- A 5-ft square tactical simulation, unless the pilot shows zones fail and the
  owner chooses a grid at SC0.
- Canvas or tile renderers, fog-of-war engines and PlaySCII-style visual polish
  before the ASCII projection is proven.
- Procedural infinite world generation, and module auto-placement rules (S5
  plan).
- Generic `memory.db` worldview tables from the old world-mapping draft. Adopt
  storage only through Narrator/Pilot ownership.
- Changing `MULTIPLAYER_MODE` or party-size checks.

## 13. Superseded drafts

`plans/version-2/mapping/mapping-overview.md`, `world-mapping.md`,
`combat-mapping.md`, `dm-local-grid.md`, `dm-regional-grid.md` and
`dm-combat-grid.md` are superseded reference. Their ideas carry forward here,
including:

- separating stage from actors;
- relative radars as a candidate format;
- campaign pegboard placement;
- a shared map host.

Their schemas, file targets and phases are not requirements.
`map-review-oct26.md` remains the deliberation record.
