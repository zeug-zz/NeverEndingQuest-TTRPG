# V2 Mapping Pilot: Spatial Grounding for the Theatre of the Players' Mind

Status: Proposed pilot plan for owner review; not implementation authorization.
Date: 2026-11-03.
Track: F (Spatial), research phase. Proposed worktree S, `feature/v2-mapping-pilot`.
Master plan: [V2 Spatial](v2-spatial.md). Program index:
[V2 narrative overview](v2-narrative-overview.md).
Deliberation record: [mapping review](version-2/mapping/map-review-oct26.md).

## 1. Overriding goal: the theatre of the players' mind

The overriding goal of the whole v2 upgrade, and of spatiality in particular, is
**the best possible gameplay UX in the theatre of the players' mind**: every
player, at the table or on a thin client, should be able to picture the same
coherent, persistent place. They should know where they stand, what they can see
and reach, where they could go, and that the world stays changed when they
change it.

Spatial data serves that imagined scene. It does not replace it:

- A correct coordinate the Narrator recites is a failure. A remembered landmark
  woven naturally into narration is a success. The aim is imaginable places,
  not map readouts.
- "Close enough" is good enough when a player could not perceive the difference
  and no rule the player relies on is broken. Python enforces only what players
  can notice and care about: reach, cover, sight, routes and committed changes.
  Everything else may stay approximate and narrative.
- The theatre of the players' mind is how the Narrator's "sentient ghost in the
  machine" (`plans/v2-narrator.md` s1) shows itself spatially. An attentive DM
  remembers where things are, as well as who people are and what happened.

The pilot exists to find the spatial context that most improves that imagined
experience at acceptable accuracy, cost and latency. It is not a contest over
mechanical correctness alone.

## 2. Authority and boundaries

- `AGENTS.md`, accepted ADRs and active OpenSpec changes take precedence. This
  plan proposes OpenSpec changes and a future `/goal`; it authorizes neither.
- Research only. The pilot changes no production defaults, `model_config.py`
  routing, published modules, installed campaign, or port 8357 behavior. Pilot
  code lives in `scripts/` capture tooling, sandbox fixtures and `tmp/` evidence.
- Python remains spatial authority. In the pilot, spatial legality is **observed,
  not enforced**: the zone ledger records what narration does but never vetoes
  it. Enforcement design belongs to the spatial build (`plans/v2-spatial.md`).
- Live captures follow `.opencode/skills/neq-capture-arena/SKILL.md` and are
  orchestrator-owned: run on a real copy under `tmp/combat_capture/`, port 8360,
  with `NEQ_OPEN_BROWSER=0` and the repository venv. Builders implement tooling;
  the primary judges the evidence.
- The pilot replaces the active `openspec/changes/mapping-research-arena-comparison`.
  That change has only a proposal and spec, and two of its facts are now stale
  (see s3.3). It is superseded rather than extended (see s9).
- Both a one-PC party (regression floor) and a four-PC party (primary shape) are
  exercised. No new party-size gates. `MULTIPLAYER_MODE` is untouched.

## 3. Starting evidence

### 3.1 Current runtime (audit 2026-11-03, read-only)

| Surface | Observation |
| --- | --- |
| Narrator spatial context | The DM note carries only the names of adjacent locations (`main.py` exits block near lines 7447-7518). |
| Atlas | `core/ai/conversation_utils.py` (near line 856) injects the full module atlas every turn, without coordinates. |
| Graph | `utils/location_path_finder.py` `LocationGraph` keys locations by bare ID across modules (collision risk, inferred, not run) and performs legacy repair writes at load (near line 316). |
| Tactical data | `utils/spatial_contract.py` `build_tactical_grid()` emits a generic 3x3 template of cover and approach labels, not prose-grounded geometry. Published modules contain zero `tacticalFeatures`. |
| Combat | No combatant positions, distances, ranges or line of sight. Turn receipts reserve an untyped `position_deltas` slot. Enemy and ally decisions are deterministic Python after the refactor. |
| Player map | None in the web UI or a thin client. |

### 3.2 Stage 1 synthetic pilot (executed 2026-10-27)

Protocol `v1-5b81f5a2`. Artifacts are in gitignored
`tmp/router-rollout/mapping-research/`. There were 36 single-shot responses
(4 conditions x 3 scenes x 3 repeats), scored strictly out of 54 per condition:

| Condition | Score | Reading |
| --- | --- | --- |
| A: current format | 26/54 | Measures facts missing from the prompt, not model weakness |
| B: explicit relationships | 51/54 | 51/51 for B, C and D once one ambiguous question is set aside |
| C: ASCII only | 53/54 | One response gave a correct route with three wrong reverse bearings |
| D: hybrid (ASCII + relationships) | 54/54 | -- |

The interim verdicts were: local grids *revise* (make origin and facing
explicit); hybrid *retain* as the next candidate; regional views, combat radars
and player maps *inconclusive*. Thirty-six blinded human-review packets exist,
but no ratings have been recorded.

**Reading:** current spatial failure is mostly *missing spatial facts and missing
in-location features*. Representation format matters much less. Stage 1 was
single-turn and synthetic. It cannot establish multi-turn continuity, persisted
state, combat behavior or player experience. Those are this pilot's questions.

### 3.3 Corrections to earlier records

- `mapping-research-arena-comparison` records G7 as BLOCKED. The archived G7
  verdict is **PASS** (primary-adjudicated), so live combat trials are unblocked.
- That change pins a specific model and profile. The pilot instead freezes the
  **current production route** after the OpenRouter rollout and records the
  resolved identity per row (s6).
- A Hindsight memory page claimed `core/mapping/` and `scripts/capture_arena.py`
  exist. Neither does. No production mapping code exists.

## 4. Questions

### Owner review direction: narrator-first mise-en-scene

The completed M1 review and nine worked redesign examples are preserved in
[SP4 owner feedback](v2-mapping-pilot-owner-feedback.md), including the final
16 original scores. Both combat fixtures scored 5/5; authored fixtures overall
scored 5.0/4.6, versus 1.55/2.09 for D1-derived sketches. The complete original
packet scored 2.625/2.875, below its frozen 3.5 thresholds.

The owner directs subsequent mapping planning toward **mise-en-scene for the
NEQ LLMs first**: coherent approaches, thresholds, boundaries, focal points,
routes and inhabitants under Python-owned topology, with player maps derived
secondarily. This calls for scene-authoring and relationship-quality work,
not merely decorating an empty grid. Builder may author initial facts;
runtime narration preserves them. Wider-world context remains compatible
with TITAN contracts and mechanical facts with Firelight/Python authority.

S will propose a separate prospective planning/evaluation follow-up using the
feedback and worked examples. The original questions, arm comparisons,
thresholds and frozen preregistration below remain historical pilot contracts;
SP3 stays INCONCLUSIVE and SP3b CLOSED BLOCKED. Neither redesigned examples
nor their separate ratings can be substituted into those results. This
direction does not complete SP4, accept ADR-0034 or authorize implementation.

### Original preregistered questions

1. **Sense of place:** In live multi-turn play, does spatial context (B or D)
   make the game feel and behave like a coherent, imaginable place compared
   with the current game (A)?
2. **Format:** Which representation gives the best imagined-scene quality per
   token: explicit relationships (B) or hybrid (D)?
3. **Theatre-of-the-mind combat:** Is a zone ledger with coarse distance bands
   "close enough"? How often does unenforced narration contradict it? How well
   do free-text moves map to a zone move? Together these answers decide how much
   Python enforcement the combat build needs.
4. **Data:** Can validated scene layouts (features, anchors, which side each
   exit is on, sightlines) be built from existing module prose? This decides
   whether published modules can be backfilled.
5. **Shared picture:** Does a schematic map sketch help players share one
   picture? The owner rates it now; testers rate it later (S4).
6. **Cost:** What are the token, latency and retry overheads per arm?

## 5. Design

### 5.1 Arms

| Arm | Exploration context | Combat context |
| --- | --- | --- |
| A: current game | Unchanged | Unchanged; the zone ledger runs in shadow for scoring only |
| B: explicit relationships | Spatial packet as concise relationship statements | Not run (budget); see below |
| D: hybrid | Spatial packet as a small ASCII sketch plus the same relationships | Zone packet: ASCII zone sketch plus engagement and band relationships |

- B and D are generated from the same fixture facts and the same knowledge
  filter, and are semantically equivalent. D may restate relationships drawn in
  the sketch but receives no extra facts.
- C (ASCII only) is dropped: D contains C's sketch, and C produced Stage 1's
  reverse-bearing errors.
- Combat runs A against D only. Stage 1 retained the hybrid, and combat evidence
  is about zones, not format. If exploration shows B clearly beats D, SP4 records
  that combat format remains open for SC0.

### 5.2 Spatial packet (prototype)

Origin and facing are explicit, following the Stage 1 *revise* verdict. The
packet holds only what the party can currently perceive or already knows:

- current location and its named anchors (features, NPC positions);
- perceived exits with their side ("the north door"), what is known behind them,
  and their state (open, locked, broken);
- visible-but-unreachable landmarks, kept separate from reachable routes;
- recent movement (where the party came from);
- a compact orientation line for the containing area instead of the full atlas.

Absence is never asserted as nonexistence. Unknown destinations are labelled
unknown. Schematic layout positions are labelled schematic; distances are given
only where the fixture authors them.

The packet carries an instruction aimed at the theatre of the players' mind:
"Use these places as the stable stage of the scene. Refer to landmarks naturally
when relevant; do not recite the map, coordinates or this note." The same
instruction text is used in B and D.

### 5.3 Sandbox injection adapter

The adapter builds the B or D packet from the fixture layout and the live
canonical party location. It places the packet where the DM-note exits list
goes, and on the matching combat prompt surface. Arm A disables it.

SP1 must first verify the seam the superseded change relied on, the
seeder/bootstrap path. Then:

- If a sandbox-only seam exists, use it with no core edits.
- If not, the minimum fallback is a single environment-gated
  `# TABLETOP MODE:` hook that defaults off and cannot activate outside the
  sandbox. That fallback needs explicit owner approval in the tooling change.
  A production default change is never acceptable.

Packets are identical across normal calls, validation retries and transitions
within a turn. The adapter logs each packet hash per turn.

### 5.4 Theatre-of-the-mind zone ledger (combat prototype)

The ledger is a Python record of named zones from the fixture stage (for
example bar, floor, balcony, stairs, doorway). Each zone has:

- adjacency, elevation and cover (none, half, three-quarters, full) per zone pair;
- occupants per zone.

Bands between combatants:

| Band | Meaning |
| --- | --- |
| Engaged | Same melee group; melee possible; leaving provokes |
| Near | About one move away; reachable with movement |
| Far | Ranged or dash only |
| Out of sight | Blocked line of sight; existence known only if previously perceived |

- **Placement:** Python places combatants at initiative from fixture rules.
- **Enemy movement:** deterministic enemy turns move by a simple labelled
  fixture policy (advance toward the nearest reachable PC zone, or hold cover).
  The current resolver has no positions, so this policy is fixture truth, not a
  claim about runtime behavior.
- **PC moves:** each PC turn yields a structured movement hint (`from`, `to`,
  `disengage`, `cover_sought`). Python checks it against adjacency and movement
  allowance, then updates the ledger. An invalid hint is recorded and has no
  mechanical effect.
- **Hint channel:** SP1 inspects the current combat response schema and
  validation, then chooses between an optional additive field (sandbox prompt
  contract only) and a small separate classifier call. A classifier call counts
  against the budget and its latency is reported.
- **Observed, not enforced:** attacks, movement and narration are never vetoed.
  Scoring counts contradictions: melee across non-engaged zones, ranged attacks
  through full cover, one actor in two zones, movement exceeding allowance,
  enemies narrated in the wrong place.

### 5.5 Arena spatial fixture extension

This is a sandbox-only fixture module seeded beside the existing Capture Arena
(CA01-CA03) into the `tmp/combat_capture/` copy. It is never listed in
`modules/published_modules.json` and never committed as a publishable module.

| Fixture | Content | Purpose |
| --- | --- | --- |
| Interior | Tavern: entrance, long table, bar, hearth, stairs, balcony, kitchen door, back door; anchor NPCs (keeper behind the bar, hooded figure by the hearth) | Stable layout, viewpoint, cross-room talk, feature change |
| Landscape | Village green, damaged bridge, woodland detour trail, ford, watchtower visible across the river but not directly reachable | Bearings, routes around an obstruction, visible versus reachable, return by another approach |
| Transition | A second area reached through one exit (village to tower approach) | Continuity across areas and a reduced atlas |
| Combat stage | Tavern zones from the interior fixture, with balcony elevation, bar cover, stairs choke and doorway | Zone ledger with two melee groups, an archer on the balcony and cover |

Each fixture carries canonical spatial truth, one stable ID per feature and an
expected-properties file used for scoring. Fixture facts are hashed and frozen
at SP0.

### 5.6 Scenario families

| ID | Live script (multi-turn) | Measures |
| --- | --- | --- |
| E1 Interior | Enter, cross to anchors, talk across the room, ask what can be seen and heard, change active PC (4-PC), return to the doorway | Layout stability, viewpoint, natural landmark use |
| E2 Landscape | Ask the way to the tower, find the bridge blocked, take the detour, describe the view, return by the ford | Bearings, routes, known versus unknown, visible versus reachable |
| E3 Transition | Leave for the second area, act there, come back | Continuity across areas; no contradictory atlas truth |
| E4 Persistence | Break or open a feature (bar the back door, smash the bridge rail), leave, return, then save and resume | The changed world stays changed |
| K1 Engagement | Several rounds: two melee groups, a balcony archer, cover use | Zone contradiction rate; narration places actors coherently |
| K2 Movement intent | "Dive behind the bar", disengage from melee, climb the stairs, push toward the archer | Free-text-to-zone accuracy; refusals and clarifications |
| K3 Enemy phase | Deterministic enemy turns narrated with zone facts | Enemies narrated where the ledger says they are |

Exploration rows run two scripts per arm and party: interior (E1 then E4) and
landscape (E2 then E3). Combat rows run one encounter covering K1-K3.

### 5.7 Offline workstreams

- **D1 data feasibility:** an offline "cartographer" pass (Python extraction
  plus one LLM call per location) proposes scene layouts for about 20 locations
  from three published modules, mixing interiors, outdoor scenes and dungeons.
  Python validates IDs, exits against the existing graph, and schema shape.
  The owner audits the precision of features, exit sides and sightlines.
  Nothing is written back to `modules/`.
- **M1 shared map sketches:** static ASCII renders from the same projections
  (party-knowledge-filtered) for the fixtures and the D1 locations. The owner
  rates them for legibility and usefulness when discussing a plan. Testers rate
  the real thing in S4. No client or `web/` work.

## 6. Matrix, budgets and stop rules

Everything in this section is pre-registered at SP0 and frozen before any
provider call. Changing it requires a recorded owner decision, not a silent
expansion.

| Block | Cells | Repeats | Rows |
| --- | --- | --- | --- |
| Exploration | Arms A/B/D x parties 1-PC/4-PC x scripts interior/landscape = 12 | n=2 on all 4-PC cells, n=1 otherwise | 18 |
| Combat | Arms A/D x parties 1-PC/4-PC = 4 | n=2 | 8 |
| Reserve | Replacement only for infrastructure failure, classified before viewing content | -- | up to 4 |
| **Total cap** | | | **30 rows** |

| Budget | Cap |
| --- | --- |
| Live attempts (all provider requests, including retries and classifier calls) | 800 total; 35 per row |
| Live wall time | 6 h total; 25 min per row |
| D1 cartographer calls | 60 |
| Model route | Current production route, frozen; resolved model, provider and fallback recorded per row |

- **Isolation:** each row starts from a fresh seeded sandbox copy. Arm order is
  counterbalanced across parties and repeats. Seeds, party fixtures and scripts
  are fixed.
- **Stop rules:**
  - A row that hits its cap, times out or loses evidence is FAIL or BLOCKED and
    preserved.
  - Content failures are results, not reasons to rerun.
  - Three consecutive infrastructure failures pause the matrix for owner review.
  - Exhausting the reserve leaves the affected cells reported as missing.
- **Serialization:** captures share port 8360 with other tracks. Before SP3
  starts, the matrix window is scheduled so it does not overlap Network or other
  live captures.

## 7. Measures and decision rules

### 7.1 Measures

**Objective** (automated where possible, primary-adjudicated against fixture
truth):

- Spatial contradiction rate per 100 spatial references: wrong exits, bearings
  or routes; moved landmarks; invented paths.
- Knowledge leakage: unperceived exits or hidden contents named; unknown
  destinations described as known.
- Continuity: return-journey consistency, feature persistence after
  leave/return and save/resume, and viewpoint correctness after a PC switch
  (4-PC).
- Combat: zone contradictions per 10 rounds; enemy placement errors; intent
  parse outcomes (exact, acceptable, wrong, refused or clarified).

**Regression guards:** mechanics errors, character-knowledge violations,
validation retries, failed turns. These must not rise against arm A.

**Cost:** input and output tokens per turn, p50/p95 turn latency, attempts per
row. Unknown cost is recorded as unknown, never as zero.

**Theatre-of-the-mind rubric** (owner, 1-5, written anchors fixed at SP0,
blinded where format permits):

1. Sense of place: does it feel like an external, persistent location?
2. Imaginability: could you picture the scene, and could you sketch it?
3. Natural use: landmarks woven into narration rather than recited.
4. Actionability: is it clear where you could go and what you could reach?
5. Continuity: does the DM remember where things are and what changed?
6. Combat clarity and flow (combat rows): positions understandable without
   slowing the game.

**Sketch test** (owner, 6 rows at most): from the transcript alone, sketch the
interior or the landscape; score anchor placement against the fixture. This
measures the theatre of the players' mind directly.

### 7.2 Proposed decision rules (ratified at SP0)

| Decision | Adopt when | Otherwise |
| --- | --- | --- |
| S2 spatial packet ships | The better of B/D cuts spatial contradictions by at least 50% versus A **and** raises the mean rubric by at least 1.0 (or reaches 4.0), with no regression-guard increase beyond one incident per arm, input tokens per turn at most +15%, and p95 latency at most +10% | Report inconclusive or revise; the packet is not adopted on token savings or accuracy alone |
| B versus D | D only if it beats B by at least 0.5 rubric points or at least 25% fewer contradictions | Default to B (cheaper); player maps render from the projection either way |
| Zones are "close enough" | Zone contradictions at most 1 per 10 rounds unenforced **and** intent parse at least 90% exact or acceptable | High contradictions with good parsing: SC1 validates legality before narration. Poor parsing: SC3 adds a clarify step and a move picker. Both poor: SC0 reconsiders granularity with the owner |
| Backfill published modules (S3) | D1 audited precision at least 85% with zero invented exits | New layouts come only from the Builder (MB1/MB2); a small hand-authored set covers pilot-critical modules |
| Shared map in S4 | Owner rates M1 sketches at least 3.5 for legibility and usefulness | S4 still ships a minimal exits panel; the map design is revised with testers |

A small pilot cannot prove universal superiority or the absence of
hallucination. Report per-family results, variance and counterexamples.
*Inconclusive* is an acceptable verdict.

## 8. Capture contract and evidence

- Evidence root: `tmp/router-rollout/mapping-pilot/<gate>/<run-id>/`. Never
  overwrite historical bundles, including `mapping-research/`.
- **Each row records:**
  - source HEAD and dirty state; worktree;
  - fixture, script and scenario hashes; arm; party; seed;
  - requested and resolved model, provider and fallback;
  - exact packets per turn;
  - transcripts, state snapshots and zone-ledger trace;
  - expected versus observed checks;
  - counts against caps; server logs; verdict.
- No secrets in artifacts. Never inspect credentials to establish readiness.
- Driver exit 0, a degraded report or green unit tests are not a PASS. Missing
  scenarios, timeouts and failed assertions leave a gate FAIL or BLOCKED.
- Prompt-only, offline (D1, M1) and live evidence stay labelled and separate.

## 9. Phases and OpenSpec changes

| Phase | Change | Scope | Exit evidence |
| --- | --- | --- | --- |
| SP0 Readiness and preregistration | Docs; supersede `mapping-research-arena-comparison` | Re-verify Arena tooling (`scripts/seed_combat_capture.py`, `scripts/capture_drive.py`, `scripts/capture_evidence.py`), the injection seam, the combat response schema and the production route. Freeze fixtures, scripts, rubric anchors, thresholds and budgets. The owner rates the 36 Stage 1 packets (can run in parallel). | Reviewed preregistration with hashes; the superseded change archived with a pointer to the new changes |
| SP1 Tooling | `v2-mapping-pilot-tooling` | Arena spatial fixture module and expected-property files; prototype layout schema; B/D projection renderers; sandbox adapter; shadow zone ledger and intent hint; scoring helpers; M1 renderer. Provider-free tests, including 1-PC and 4-PC seeding and arm A no-op proof. | Focused tests and ASCII compliance pass; dry seeding of all fixtures; no production default changed |
| SP2 Offline | Within the tooling change, or a small follow-up | D1 cartographer run (60 calls or fewer) and owner audit; M1 sketch set | Audit sheet with precision; rated sketches |
| SP3 Live matrix | `v2-mapping-pilot-execution` | Orchestrator runs the s6 matrix | Per-row bundles; caps respected; every cell is PASS, FAIL, BLOCKED or missing, explicitly |
| SP4 Adjudication and gate | Same change | Scoring, owner rubric and sketch tests, decision report, draft ADR on spatial authority and projections, inputs to S1, S2, SC0/SC1 and S3 | Owner decision gate recorded; spatial plan updated from provisional to decided |

## 10. Deliverables and decision gate

1. A decision report covering Q1-Q6 with retain, revise, reject or
   inconclusive for each of: exploration packet, format, zone combat, backfill,
   shared map.
2. A draft ADR: Python spatial authority, projection-per-audience, schematic
   versus metric, observed versus enforced legality, and the "close enough" rule.
3. Concrete inputs:
   - layout schema draft (S1);
   - packet format and caps (S2);
   - zone and band rules plus the enforcement level (SC1);
   - backfill route (S3);
   - map sketch conventions (S4).
4. Owner ratings for the Stage 1 packets, live transcripts and M1 sketches.

At the gate the owner chooses the format, the combat granularity and enforcement
level, and the data pipeline. Only then do S1 and the Narrator worktree R start
(`plans/v2-narrative-overview.md` s7).

## 11. Candidate goal for worktree S

### Objective

Determine, through preregistered live Capture Arena play with one-PC and
four-PC parties, which spatial context best improves gameplay UX in the theatre
of the players' mind. Compare the current game with explicit-relationship and
hybrid spatial packets, test a theatre-of-the-mind zone ledger for combat, and
assess layout backfill feasibility and shared map sketches. Deliver an
evidence-backed decision report, a draft spatial ADR and concrete inputs for the
v2 spatial build, without changing production behavior.

### Immutable completion criteria

1. SP0 preregistration (fixtures, scripts, rubric anchors, thresholds, budgets,
   frozen route) is reviewed before any provider call. The superseded change is
   archived with a pointer.
2. Tooling has passing provider-free tests and ASCII compliance, proves arm A is
   a no-op, and changes no production default.
3. The s6 matrix is executed within caps. Every cell is reported PASS, FAIL,
   BLOCKED or missing with preserved evidence. Nothing is silently waived.
4. D1 and M1 are completed and owner-audited, or reported blocked with evidence.
5. Owner ratings exist for the live transcripts (and Stage 1 packets). No
   ratings are invented.
6. The decision report, draft ADR and S1/S2/SC1/S3/S4 inputs are reviewed at the
   owner decision gate.

The goal may close unmet only with a concrete blocker and evidence. An
*inconclusive* verdict with complete evidence satisfies criteria 3 and 6.

## 12. Risks and open items

- **Injection seam:** if no sandbox-only seam exists, the env-gated hook needs
  owner approval (s5.3).
- **Intent channel:** a classifier call may add latency that SC1 must budget
  for. An additive schema field may disturb validation; SP1 decides.
- **Blinding:** ASCII sketches reveal the arm, so human blinding is partial.
  Record this.
- **Fixture bias:** purpose-built fixtures are cleaner than published modules.
  D1 tests the real data gap separately.
- **Capture contention:** SP3 must be scheduled around Network live work on
  port 8360.
