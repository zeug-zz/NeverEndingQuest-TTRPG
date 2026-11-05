# V2 Mapping Pilot Preregistration

Status: Preregistration for owner review; frozen on owner approval; no provider call before approval

This preregisters the live spatial-context comparison and shadow combat-zone
ledger described by `plans/v2-mapping-pilot.md`. It is research-only: no
production default, installed campaign, published module, port 8357 behavior, or
production spatial authority changes here. Python remains authoritative; spatial
legality is observed, not enforced.

## Readiness record (re-checked against this worktree)

- **Seeder and sandbox:** `scripts/seed_combat_capture.py` rebuilds
  `tmp/combat_capture/` and copies application/runtime subsets plus only
  `modules/Capture_Arena` as its module tree (`_copy_runtime`, lines 221-251;
  explicit module copy at line 246). It patches sandbox `WEB_PORT = 8360`
  (lines 254-262) and `ENABLE_COMBAT_TURN_TRACE = True` (lines 291-302). SP1
  must extend the seeder to copy and seed the spatial fixture module; this SP0
  patch does not change the seeder.
- **Party fixtures and IDs:** `--prepare` accepts only `--party 1` or `--party 4`
  (`scripts/seed_combat_capture.py:1195-1205,1236`). P1 is Acheron; P4 is
  Acheron, Merisiel, Kira, Vitreol (`scripts/combat_latency_fixtures.py:35-41`;
  `scripts/seed_combat_capture.py:665-668`). The current seeder has a fixed
  `SEED_TIMESTAMP` (`scripts/seed_combat_capture.py:72,825`) but no general
  `--seed` option. The fixed seed values below are preregistered pilot seeds;
  SP1 must wire them into sandbox fixture seeding and record the effective seed.
  Existing Capture Arena location IDs use the `CA` form: CA01, CA02, CA03
  (`modules/Capture_Arena/areas/CTR001_BU.json:11,44,88`).
- **Sandbox injection seam:** `main.py` imports
  `build_enhanced_dm_note` (line 189) and calls it for the exploration path
  (lines 8035-8042). `core/combat/prompts.py` builds the prompt through
  `assemble_combat_prompt` (lines 763-773 and 834-864). A sandbox-only
  `scripts/` launcher can wrap the imported DM-note function for both party
  sizes and the combat prompt surface without editing core files. No
  `# TABLETOP MODE:` hook is expected. If this seam proves unavailable, an
  environment-gated core hook is a fallback only after explicit owner approval;
  do not add it silently.
- **Combat response contract:** no combat response JSON schema file is used for
  this path; JSON shape and action checks are in code (`core/combat/turn.py:
  1001-1025`; `core/combat/validation.py:138-187,319ff`). The checked contract
  permits an additive optional top-level `movement_hint` in the sandbox prompt
  contract, but not a new action type. SP1 must verify the exact response path
  before implementation. Preferred channel: additive optional `movement_hint`
  field in the sandbox prompt contract only. Fallback: one separate classifier
  call, counted against attempt and latency caps. SP1 decides with evidence.
- **Route:** `model_config.py` selects `ACTIVE_PROFILE = "production-auto"`
  (lines 151,158-204); `openrouter/auto` is used for both tiers and the task
  cost tiers are in lines 208-216. On one eligible failover, the router selects
  `openai/fallback`, using `gpt-6-luna` (`model_config.py:5,186-204`;
  `utils/llm_router.py:427-517,699-711`). OpenRouter Auto selects a downstream
  model per call, a declared confound. Freeze the profile at the SP0 merge
  commit; do not pin a downstream model or set per-arm overrides. Record
  requested model, resolved model, transport/provider, observed upstream
  provider, fallback status and task for every call. Report resolved-model
  distributions by arm and flag imbalance as specified below.
- **Stage 1 review material:** the read-only source bundle is
  `../NeverEndingQuest/tmp/router-rollout/mapping-research/`. Its 36 human
  review packets are in
  `../NeverEndingQuest/tmp/router-rollout/mapping-research/pilot-analysis-v1-5b81f5a2/human-review/`;
  the source worksheet is
  `../NeverEndingQuest/tmp/router-rollout/mapping-research/pilot-analysis-v1-5b81f5a2/human-review/ratings-template.md`.
  Do not edit those historical files or fill ratings in this preregistration.

## Arms

| Arm | Exploration context | Combat context |
|---|---|---|
| A: current game | Unchanged | Unchanged; the zone ledger runs in shadow for scoring only |
| B: explicit relationships | Spatial packet as concise relationship statements | Not run (budget) |
| D: hybrid | Spatial packet as a small ASCII sketch plus the same relationships | Zone packet: ASCII zone sketch plus engagement and band relationships |

B and D use the same fixture facts and knowledge filter and are semantically
equivalent. D may restate relationships drawn in its sketch but gets no extra
facts. C (ASCII only) is dropped: D contains C's sketch, and C produced Stage 1
reverse-bearing errors. Combat runs A against D only; if exploration shows B
clearly beats D, SP4 records combat format as open for SC0.

## Spatial packet contract

The packet contains only facts the party can currently perceive or already
knows: current location and named anchors (features and NPC positions), perceived
exits with side/state/known destination, visible-but-unreachable landmarks kept
separate from routes, recent movement (where the party came from), and a compact
orientation line for the containing area instead of the full atlas. The
knowledge filter is party- and viewpoint-aware; hidden contents and unperceived
exits never enter the packet. Unknown destinations are labelled `unknown`.
Absence from the packet never means nonexistence. Schematic layout positions are
labelled `schematic`; distances appear only when explicitly authored in the
fixture. Packets are identical across normal calls, validation retries and
transitions within a turn; the adapter logs a packet hash per turn.

The shared B/D instruction is exactly:

> Use these places as the stable stage of the scene. Refer to landmarks naturally
> when relevant; do not recite the map, coordinates or this note.

## Zone ledger contract

The ledger records named fixture zones, pairwise adjacency, elevation, pairwise
cover and occupants. It is Python-owned test evidence only and never vetoes
narration, attacks or movement.

| Band | Meaning |
|---|---|
| Engaged | Same melee group; melee possible; leaving provokes |
| Near | About one move away; reachable with movement |
| Far | Ranged or extended movement only |
| Out of sight | Blocked line of sight; existence known only if previously perceived |

Python places combatants at initiative from the fixture rules. The exact
initial placements, adjacency graph, enemy policy and movement allowance are in
`fixtures/combat_stage_tavern.json`. Melee groups advance by the deterministic
fixture policy; the balcony archer holds its authored position/cover. Standard
PC movement is one adjacent zone step; extended movement is two adjacent zone
steps. A PC-turn movement hint has `from`, `to`, `disengage` and `cover_sought`.
An invalid hint is recorded and has no mechanical effect. The resolver has no
positions; this enemy policy is fixture truth, not a claim about current runtime
behavior.

Movement-parse outcomes are exactly `exact`, `acceptable`, `wrong`, `refused`,
or `clarified`. `Exact` matches the intended destination and material flags;
`acceptable` is a legal equivalent route/zone that preserves intent; `wrong`
selects an incompatible destination or drops a material flag; `refused` yields
no usable move; `clarified` asks the player to clarify before a move is produced.

## Fixtures and scripts

The four canonical, sandbox-only truth files are:

1. `fixtures/interior_tavern.json`: entrance, long table, bar, hearth, stairs,
   balcony, kitchen door and back door; keeper behind the bar and hooded figure
   by the hearth.
2. `fixtures/landscape_village.json`: village green, damaged bridge, woodland
   detour, ford and a watchtower visible across the river but not directly
   reachable.
3. `fixtures/transition_tower_approach.json`: second area reached from the
   village; a known return by the ford and a reduced local orientation.
4. `fixtures/combat_stage_tavern.json`: tavern zone ledger with two melee groups,
   a balcony archer, cover, elevation, initial P1/P4 placements and deterministic
   enemy policy.

`scripts/interior.json` runs E1 then E4 in 8 model-bearing turns. It includes a
4-PC active-character switch and a save/restart/resume lifecycle checkpoint
without reseeding. `scripts/landscape.json` runs E2 then E3 in 8 turns.
`scripts/combat.json` runs K1-K3 in one encounter in 7 turns, including all four
K2 utterances from s5.6. All actors use the seeded P1/P4 names. Control actions
such as active-PC changes and save/resume are not model-bearing turns.

## Matrix, order and budgets

The 18 exploration rows comprise A/B/D x P1/P4 x interior/landscape, with one
repeat for each P1 cell and two repeats for every P4 cell. The 8 combat rows
comprise A/D x P1/P4, n=2. Four additional slots are replacements only for
pre-content-classified infrastructure failures. The table lists all 30 slots;
R01-R04 inherit the failed row's arm, party, script and repeat and receive a
new fixed seed. They never add a new matrix cell.

Fixed seeds are shared within each matched arm group (common random numbers),
and differ between repeats/groups. Run order is static, not randomized after
seeing content. The six three-arm exploration cohorts use these orders:
`A-B-D`, `D-B-A`, `B-D-A`, `A-D-B`, `D-A-B`, `B-A-D`. Each arm appears twice
in each ordinal position. The four A/D combat cohorts alternate so each arm
appears first twice. This counterbalances position across parties, scripts and
repeats while retaining a deterministic schedule.

| Row ID | Block | Arm | Party | Script | Repeat | Fixed seed | Run order |
|---|---|---:|---:|---|---:|---:|---:|
| E01 | Exploration | A | P1 | interior.json | 1 | 5101 | 01 |
| E02 | Exploration | B | P1 | interior.json | 1 | 5101 | 02 |
| E03 | Exploration | D | P1 | interior.json | 1 | 5101 | 03 |
| E04 | Exploration | D | P1 | landscape.json | 1 | 5102 | 04 |
| E05 | Exploration | B | P1 | landscape.json | 1 | 5102 | 05 |
| E06 | Exploration | A | P1 | landscape.json | 1 | 5102 | 06 |
| E07 | Exploration | B | P4 | interior.json | 1 | 5103 | 07 |
| E08 | Exploration | D | P4 | interior.json | 1 | 5103 | 08 |
| E09 | Exploration | A | P4 | interior.json | 1 | 5103 | 09 |
| E10 | Exploration | A | P4 | interior.json | 2 | 5104 | 10 |
| E11 | Exploration | D | P4 | interior.json | 2 | 5104 | 11 |
| E12 | Exploration | B | P4 | interior.json | 2 | 5104 | 12 |
| E13 | Exploration | D | P4 | landscape.json | 1 | 5105 | 13 |
| E14 | Exploration | A | P4 | landscape.json | 1 | 5105 | 14 |
| E15 | Exploration | B | P4 | landscape.json | 1 | 5105 | 15 |
| E16 | Exploration | B | P4 | landscape.json | 2 | 5106 | 16 |
| E17 | Exploration | A | P4 | landscape.json | 2 | 5106 | 17 |
| E18 | Exploration | D | P4 | landscape.json | 2 | 5106 | 18 |
| C01 | Combat | A | P1 | combat.json | 1 | 5201 | 19 |
| C02 | Combat | D | P1 | combat.json | 1 | 5201 | 20 |
| C03 | Combat | D | P1 | combat.json | 2 | 5202 | 21 |
| C04 | Combat | A | P1 | combat.json | 2 | 5202 | 22 |
| C05 | Combat | D | P4 | combat.json | 1 | 5203 | 23 |
| C06 | Combat | A | P4 | combat.json | 1 | 5203 | 24 |
| C07 | Combat | A | P4 | combat.json | 2 | 5204 | 25 |
| C08 | Combat | D | P4 | combat.json | 2 | 5204 | 26 |
| R01 | Reserve | inherit | inherit | inherit | inherit | 5901 | 27 if used |
| R02 | Reserve | inherit | inherit | inherit | inherit | 5902 | 28 if used |
| R03 | Reserve | inherit | inherit | inherit | inherit | 5903 | 29 if used |
| R04 | Reserve | inherit | inherit | inherit | inherit | 5904 | 30 if used |

`counterbalance.json` is the machine-readable source of this same table. The
fixed order controls planned rows; reserve order is activation order only.

| Budget | Cap |
|---|---:|
| Live provider attempts, including validation retries and classifier calls | 800 total; 35 per row |
| Live wall time | 6 hours total; 25 minutes per row |
| D1 cartographer calls | 60 |

Expected attempts use an explicit planning assumption of about 3 provider calls
per model-bearing turn, including normal validation/retry overhead. Exploration
scripts have 8 turns: about 24 attempts per row. Combat has 7 turns: about 21
attempts per row, plus up to 4 separate K2 classifier calls if SP1 selects the
fallback channel, for 25 expected attempts. Thus expected attempts are at most
25 per planned row; all 26 planned rows are about 600 calls without a separate
classifier and about 632 with one. Four used reserve rows add at most about 100
expected calls, keeping the expected matrix total around 732 under the 800 cap.
These are planning estimates, not waivers of hard caps. Actual counts are
recorded; unknown counts remain unknown.

Each row starts from a fresh seeded sandbox copy. Use the repository venv,
`NEQ_OPEN_BROWSER=0`, and port 8360 only. No 8357 inspection or use. Captures are
serialized and the SP3 window is booked with the Overseer so it does not overlap
Network or other live captures.

## Stop rules and replacement classification

Apply these rules without changing their meaning:

- A row that hits its cap, times out or loses evidence is FAIL or BLOCKED and
  preserved.
- Content failures are results, not reasons to rerun.
- Three consecutive infrastructure failures pause the matrix for owner review.
- Exhausting the reserve leaves the affected cells reported as missing.

Before opening any transcript, narration, response body or content-derived
assertion, the operator records `INFRASTRUCTURE`, `CONTENT/RESULT`, or
`UNRESOLVED` using only process/transport/provider status, timestamps, and
artifact-presence metadata. An infrastructure classification requires objective
evidence that no usable model response was available because of sandbox
prepare/boot/listener failure on 8360; socket/control transport failure; DNS,
TLS, connection-reset or provider HTTP 429/5xx failure; or evidence writer/log
capture failure independent of response content. Record the concrete error
class/status and source log. A timeout is infrastructure-eligible only if those
logs establish a transport/service failure before any usable response; ordinary
slow generation or an application/model hang without such evidence remains a
row timeout, not a replacement entitlement. A returned refusal, malformed or
invalid content, validation retry, contradiction, poor narration, wrong
movement, or other response-quality result is content/result, never
infrastructure. If classification is ambiguous, use `UNRESOLVED`, preserve the
row, and request owner adjudication; do not use reserve pending that decision.

Every failed row and its original evidence remain preserved. Only a row
classified infrastructure before content review can consume the next reserve
slot; the replacement inherits that exact cell and repeat, has a unique run ID
and the reserve seed, and does not erase the original FAIL/BLOCKED record. No
content failure is rerun. Three consecutive infrastructure failures pause
before another row is started.

## Measures and operational definitions

All objective scoring is automated where possible and primary-adjudicated
against the frozen fixture truth. The scorer reads every assistant turn in the
script; user utterances and control operations are not scored as narration.

- **Spatial reference:** one distinct spatial proposition in assistant output
  that asserts a named anchor's position/relative bearing, an exit's side/state
  or destination, a route/connectivity, visibility/reachability, an occupant's
  position, movement from/to, a distance, cover, elevation or line of sight.
  Split compound statements into atomic propositions; count repeated assertions
  once per occurrence. The denominator is all such propositions, including
  correct and uncertain references. A question or explicitly marked uncertainty
  is not an asserted fact.
- **Spatial contradiction:** a spatial reference that conflicts with fixture
  truth or a previously established state. Categories are wrong exit/side/state
  or destination; wrong bearing/route/connectivity; moved or contradictory
  landmark/occupant; invented exit/path/feature; false visible/reachable or
  sightline claim; unsupported authored distance; or failure to preserve a
  committed feature change. Count one contradiction per false atomic
  proposition, not per word. Rate = `100 * contradictions / spatial references`.
  If the denominator is zero, report `not estimable`, never zero.
- **Knowledge leakage:** any assistant assertion that reveals an unperceived
  exit, hidden content, or an unknown destination as known. Report count and
  rate per 100 assistant turns; do not infer that omitted facts do not exist.
- **Continuity:** report three separate checks, not a blended score: (1) return
  journey preserves fixture routes and relevant approach; (2) changed back-door
  state persists after leave/save/resume/return; (3) after the 4-PC active-PC
  switch, view/position facts remain stable and do not teleport or contradict
  the new actor's viewpoint. A check passes only when every required assertion
  in that script's `expected_checks` is true.
- **Combat contradictions:** one event per observed contradiction, with these
  categories: melee narrated across non-engaged zones; ranged attack narrated
  through full cover or blocked line of sight; one actor assigned two zones at
  once; movement exceeding fixture allowance or non-adjacent movement; enemy
  narrated in a zone inconsistent with the ledger/policy; and false elevation,
  cover or engagement relation. Rate = `10 * contradictions / observed combat
  rounds`; report categories and the raw numerator/denominator.
- **Intent parsing:** each of the four K2 utterances receives exactly one class
  (`exact`, `acceptable`, `wrong`, `refused`, `clarified`) by comparison with
  its expected movement hint in `combat.json`. Accuracy numerator is
  exact+acceptable; denominator is all four utterances, including refusals and
  clarifications. Report the class counts and exact+acceptable percentage.
- **Regression guards:** count mechanics errors, character-knowledge
  violations, validation retries and failed turns per row. Compare each guard
  separately on matched completed rows; a candidate may have at most one more
  incident than A in each guard category. Do not offset one guard with another.
- **Cost:** record input/output tokens per model-bearing turn, p50/p95 turn
  latency, total row attempts and classifier-call latency where applicable.
  Allocate every classifier call to its triggering turn. Unknown or incomplete
  token/cost data is `unknown`, never zero.
- **Route confound:** report the per-arm distribution of requested model,
  resolved model, transport/provider, observed upstream provider and fallback
  status over calls. Flag imbalance if any resolved-model share differs from A
  by 10 percentage points or more, or if the per-call fallback share or
  unknown-model share differs by arm. Do not pin the downstream model; discuss
  the imbalance as a confound and report per-family results.

## Proposed decision rules (for owner ratification)

Comparisons use completed matched cells only. A matched exploration cell is
party + script + repeat; a matched combat cell is party + repeat. The analysis
publishes missing/failed cells and does not impute them. If a criterion cannot
be calculated, report it as not estimable and the decision as inconclusive.

| Decision | Adopt when | Otherwise |
|---|---|---|
| S2 spatial packet ships | The better of B/D cuts spatial contradictions by at least 50% versus A **and** raises the mean rubric by at least 1.0 (or reaches 4.0), with no regression-guard increase beyond one incident per arm, input tokens per turn at most +15%, and p95 latency at most +10% | Report inconclusive or revise; the packet is not adopted on token savings or accuracy alone |
| B versus D | D only if it beats B by at least 0.5 rubric points or at least 25% fewer contradictions | Default to B (cheaper); player maps render from the projection either way |
| Zones are "close enough" | Zone contradictions at most 1 per 10 rounds unenforced **and** intent parse at least 90% exact or acceptable | High contradictions with good parsing: SC1 validates legality before narration. Poor parsing: SC3 adds a clarify step and a move picker. Both poor: SC0 reconsiders granularity with the owner |
| Backfill published modules (S3) | D1 audited precision at least 85% with zero invented exits | New layouts come only from the Builder (MB1/MB2); a small hand-authored set covers pilot-critical modules |
| Shared map in S4 | Owner rates M1 sketches at least 3.5 for legibility and usefulness | S4 still ships a minimal exits panel; the map design is revised with testers |

The decision calculations are fixed as follows:

1. Select the exploration candidate using the B-vs-D rule first. On complete
   matched exploration cells, compute each arm's pooled contradiction rate as
   `100 * sum(contradictions) / sum(spatial references)`. D beats B if the
   paired-row mean of its five non-combat rubric dimensions is at least 0.5
   points higher, or if its pooled contradiction rate is at least 25% lower
   (`100 * (B_rate - D_rate) / B_rate >= 25`). If B's rate is zero, the
   contradiction condition is not met. If neither threshold establishes D as
   better, choose B as the preregistered cheaper default; if neither metric is
   estimable, report the comparison inconclusive and retain B only as the
   provisional default, not as demonstrated superiority.
2. For S2, compare the selected candidate with A on the same complete matched
   exploration cells. Contradiction reduction is
   `100 * (A_rate - candidate_rate) / A_rate`; if A_rate is zero or unavailable,
   reduction is not estimable and S2 cannot pass. A negative reduction means
   worsening. Rubric mean is the unweighted arithmetic mean of each row's mean
   over dimensions 1-5, then the unweighted mean over matched rows; dimension 6
   is reserved for combat. The rubric condition is
   `(candidate_mean - A_mean >= 1.0) OR (candidate_mean >= 4.0)`.
3. For input tokens per turn, divide total recorded input tokens (including
   classifier prompts allocated to the turn) by completed model-bearing turns
   in the matched arm. The candidate must be `<= 1.15 * A`. For latency, use
   completed-turn end-to-end wall latency and nearest-rank p95 (sorted value at
   `ceil(0.95*n)`) over the same matched arm turns; candidate must be
   `<= 1.10 * A`. Unknown data fails the gate as not estimable, not as zero.
4. Regression guards use aggregate incident counts within the same matched
   exploration set (B/D vs A) and, separately, the matched combat set (D vs A).
   Each of the four guard categories must be no more than A + 1; B has no combat
   rows, so no B combat claim is made.
5. For zones, use the combat A/D rows only. Zone contradiction rate is
   `10 * sum(zone contradictions) / sum(observed rounds)`; intent success is
   `(exact + acceptable) / 4` per row and pooled over completed matched rows.
   The thresholds are `<= 1.0` contradictions per 10 rounds and `>= 90%` intent
   success. Refusals and clarifications remain in the denominator.

A small pilot cannot establish universal superiority or absence of
hallucination. Report per-family results, variance and counterexamples.
Inconclusive is an acceptable verdict.

## Capture evidence and blinding

Evidence root: `tmp/router-rollout/mapping-pilot/<gate>/<run-id>/`. Never
overwrite historical bundles, including `mapping-research/`. Each row records:
source HEAD and dirty state/worktree; fixture, script and scenario hashes; arm,
party and seed; requested/resolved model, provider and fallback per call; exact
packets per turn and packet hashes; transcripts; state snapshots and zone-ledger
trace; expected versus observed checks; counts against caps; server logs; and
verdict. No secrets are included. Prompt-only, offline (D1/M1) and live evidence
remain separately labelled. A driver exit code, degraded report or green tests
are not a PASS. Missing scenarios, timeouts and failed assertions leave a gate
FAIL or BLOCKED.

Blinding is partial. Hide arm labels, row order, model/provider metadata and
fixture answer keys from raters until ratings are locked. ASCII sketches reveal
the format and therefore may reveal D; record the limitation and do not claim
full blinding. Content-only ratings do not excuse factual errors; factual
adjudication stays separate.

### Stage 1 owner ratings

The historical Stage 1 packet set contains 36 response packets at
`../NeverEndingQuest/tmp/router-rollout/mapping-research/pilot-analysis-v1-5b81f5a2/human-review/`.
Use the 36 opaque-ID packet `.md` files there and the read-only worksheet
`../NeverEndingQuest/tmp/router-rollout/mapping-research/pilot-analysis-v1-5b81f5a2/human-review/ratings-template.md`.
The companion historical rubric is in the same directory as `rubric.md`. Do
not edit source packets or the template, do not copy ratings into this
preregistration, and do not fill or invent any rating now. When the owner
authorizes rating, make one separate worksheet copy per opaque response ID,
record a 1-5 rating and evidence quote for each historical dimension, and keep
factual answer-key scoring separate. Preserve `not rateable` rather than
imputing a score. The 5-dimension Stage 1 instrument is historical and is not
replaced by the 6-dimension live-pilot rubric below.

## Preregistration choices

- Use the collision-checked `MPV2_` location/feature namespace; keep fixture
  geometry schematic and authored distances empty because none are needed by
  these scripts.
- Share fixed seeds across matched arms and use new seeds across repeats. The
  existing seeder has no generic pilot `--seed`; adding that support and copying
  the sandbox fixture module belong to SP1.
- Use a six-cohort balanced three-arm schedule and alternating A/D combat
  order. R01-R04 replace only pre-content-classified infrastructure rows.
- Use 8/8/7 model-bearing turns for interior/landscape/combat. The separate
  classifier fallback gets four extra calls per combat row, keeping expected
  attempts at 25 or fewer per row under the stated assumption.
- Flag resolved-model imbalance at a 10 percentage-point share difference from
  A, or any arm difference in fallback/unknown-model incidence; preserve
  production-auto rather than pinning Auto Router's downstream choice.
- Define one normal move as one adjacent zone edge and one extended move as two;
  define enemy target/path tie breaks and the narrow infrastructure-replacement
  rule in the frozen fixture/protocol rather than retroactively.
- Score sketches against named anchor placement, select six balanced rows in
  `rubric.md`, and keep historical Stage 1 ratings separate from live ratings.

## Owner review items

- Approve the route-confound handling, including no model pinning, per-call
  identity capture, and the imbalance flag.
- Ratify the proposed decision rules, matched-cell handling and computations.
- Approve the fixture facts, fixed scripts, movement allowances and seed policy.
- Confirm that the sandbox-only injection seam is sufficient and no core hook is
  expected; approve any hook fallback explicitly before SP1 edits.
- Approve the attempt/time budgets and pre-content infrastructure
  classification/replacement rules.
- Book the port 8360 window with the Overseer before SP3; confirm no overlap with
  Network or other live captures.
- Authorize the separate Stage 1 owner ratings; no ratings are filled here.

## Hashes

`MANIFEST.sha256` hashes every other file in this directory using paths relative
to this directory. Regenerate after any content change, from the repository
root, with:

```sh
cd plans/v2-mapping-pilot-prereg
shasum -a 256 README.md rubric.md fixtures/*.json scripts/*.json counterbalance.json > MANIFEST.sha256
shasum -a 256 -c MANIFEST.sha256
```

The manifest itself is intentionally not self-hashed.
