# SP4 owner review: development feedback

Append-only review notes from the guided M1 review. These are owner feedback
for subsequent planning and building, not a preregistration amendment, ADR
acceptance, implementation authorization, or evidence of delivered behavior.
Canonical numeric ratings remain in worktree S's
`tmp/router-rollout/mapping-pilot/m1/m1-20261105-02/ratings.csv`.

## Review notes: graph-paper layouts and narrative freedom

- The intended presentation is a basic graph-paper spatial model, not a
  commercial illustrated dungeon map. Fixture tavern layouts match the
  owner's intent.
- The narrator should elaborate atmosphere, scenery and story around fixed
  spatial facts. For example, describe approaching a looming tower along a
  path, but keep its authored north gate north rather than moving it west.
- Preserve useful relative positions without demanding exact distances or
  exhaustive deterministic modelling. Do not confuse scenic detail with
  positional precision. Firelight/mechanical consumers must use appropriate
  explicit mechanical data, not infer distances from schematic cells.

## Review notes: empty grids and features spanning cells

- The owner questioned empty grids: the causeway sketch's spatial information
  is entirely in its accompanying descriptions. A score for useful prose is
  not proof that the grid itself contributes useful placement.
- Trailhead: the shrine and camp lack useful grid placement. The shrine is in
  a central marker; the source does not thereby establish that marker at the
  scene centre. Camp NW/NE placement cannot be invented as an extraction fact.
- Corn arena: clarify that the Spectral Gallery means ghostly spectators, not
  necessarily a structure. Their relationship to the arena boundary and corn
  wall should be represented only if authored or explicitly established.
- Paths, causeways, rivers and enclosing boundaries may span multiple cells.
  Owner example: a causeway through the north/centre/south cells with marsh
  on either side. If cardinal orientation is not established, distinguish
  schematic orientation from world-compass truth.
- Presentation correction: the assistant initially drew the arena throne in
  the north row, although the artifact places it centrally. The owner revised
  the arena score to 3/3 after clarification. Future review shows exact text.

## Review notes: regional context, scale and cumulative discovery

- Owner asks that scene grids fit the wider adventure and regional route
  context: does crossing the causeway permit travel north to the next scene?
  A scene sketch alone cannot answer that question.
- Owner proposes a regional nine-cell schematic, for example causeway in the
  centre with castle or trail-to-castle north or beyond. This is an example
  of desired hierarchy, not a claim about the causeway module's authored map.
- Grid scale is flexible: room, scene and regional views are different
  scopes, not uniformly sized movement squares. Make scope/orientation and
  links between views explicit; do not silently derive mechanical distances.
- Desired player map is cumulative across the adventure, revealing known
  routes and visited scenes from adventure start to current location, rather
  than replacing the whole map with each local scene. Preserve rumours,
  discovered and visited distinctions and avoid revealing hidden geography.
- The same canonical places, routes, stable directions and traversal
  prerequisites must inform the LLM narrator as well as the player map.
  Give the narrator bounded current-scene and wider-route context plus lookup
  for distant places; do not send the entire accumulated map on every turn.
- Planning follow-up: reconcile this desired cumulative regional view with
  `plans/v2-spatial.md` S2 (narrator packet and spatial lookup), S4
  (knowledge-filtered player map), and S5 (regional layer, currently later
  and requiring its own plan). Do not silently pull S5 into S4 or change
  frozen pilot artifacts. Review mechanical consumers with the Firelight
  track when contracts are defined.

## Review notes: market AB01 and owner-proposed example

- Original market sketch rated 2/2. The owner remembers running the scene as
  a village market bordering fields with a scarecrow, specific NPC vendors,
  and surrounding village buildings. A central label "Display Tables" does
  not capture that imagined scene or the relationships useful for narration.
- Owner-proposed illustrative placement: field fences in N/NW/W/SW;
  scarecrow staring ominously from NW; village tavern or housing in NE/E/SE,
  with stalls in those eastern cells; display tables in C. This is a design
  example supplied during review, not verified module extraction or a change
  to the original sketch, fixture, or pilot evidence.
- Mayor in C is a question, not a confirmed placement. Vendor names and
  individual stall assignments likewise need source verification or explicit
  authoring before being treated as canonical facts.
- The example should demonstrate a coherent scene boundary (fields versus
  village), identifiable participants, and positional relationships, while
  keeping narrator freedom over atmosphere. Original numeric rating remains
  attached to the original artifact, not the improved example.
- Owner endorsed the redesign as an example of a better grid and proposed
  stalls in N/NW/W/SW as well: the fences form the outer boundary behind
  those stalls, with fields beyond. A cell can contain both a boundary and
  an interior feature; the renderer should preserve their relationship.

### Illustrative better market grid (owner-endorsed; not source-verified)

North up; schematic, not to scale. Fields beyond the north/west fences;
village buildings to the east. Stall occupants and mayor position unverified.

```text
NW: fence; stall inside; scarecrow beyond at field edge
N:  fence; stall inside; fields beyond
NE: village housing; stall in front
W:  fence; stall inside; fields beyond
C:  display tables; open market square; mayor placement unconfirmed
E:  illustrative tavern frontage; stall in front
SW: fence; stall inside; fields beyond
S:  surroundings unspecified
SE: village housing; stall in front
```

## Review notes: village square AB02

- Original #9 rated 1/1: an empty grid has no useful spatial placement on its
  own. The owner rates the following contextual expansion 5/5 as a design
  example, not as the original M1 artifact. That separate example rating must
  not enter the original packet's mean or replace the original 1/1.
- Owner recollection: move from market square into village square proper,
  possibly up a slight incline. The incline is uncertain and needs checking.
- Proposed placement: market-side stalls in NW/W/SW; buildings around
  NW/N/NE/E/SE/S. Buildings form boundaries, with square space and lanterns
  also occupying those outer cells, rather than all open space confined to C.
  Lanterns throughout the perimeter are useful; C may remain open.
- Tavern and church locations need source verification. The owner recalls
  that the pastor's church may instead be on the village outskirts.
- Desired spatial experience: stand outside the tavern in the village square
  while retaining sight/sound of the adjacent market. Visibility/audibility
  across scene boundaries should be represented where supported.
- Direction reconciliation remains open: the proposed stalls are NW/W/SW,
  but the owner's final example refers to tavern W and market stalls beyond
  E. Earlier illustrative market placement put tavern frontage E. Do not
  silently choose between these directions or encode a canonical transition
  before checking source geography and agreeing a consistent orientation.
- Preserve stable building IDs across scene views; distinguish a building's
  boundary/frontage from traversable square space in the same schematic cell.
- Owner clarification: market stalls are beyond W, not E. This resolves the
  market-side direction in the preceding example; the earlier conflicting
  wording is retained only as review history. Tavern frontage in W is part
  of the current illustrative village-square layout, not verified module data.
- Owner requests a path toward the church in NE. This is a proposed schematic
  exit, with the church beyond the scene rather than necessarily in the square.
  Verify its location and route against the module before canonical authoring.

## Owner clarification: narrator-first spatiality and linked scene views

- The owner explicitly prioritizes optimizing spatial understanding for NEQ's
  LLMs. Player-facing maps are a subsequent resource derived from that spatial
  model, not the primary reason to build it. Read the M1 visual ratings as
  owner judgments of the artifacts, not proof of improved narrator behavior;
  narrator improvements still require their own evidence.
- Useful grids give the narrator stable relationships around which it can
  elaborate a story: stalls inside fences, buildings bounding traversable
  square space, and routes connecting scenes. Visual polish is secondary.
- The illustrative market and village-square layouts agree on the broad
  connection: the village square is east of the market; the market is west
  of the village square. Preserve reciprocal directions across views.
- The market's eastern tavern frontage and square's western tavern frontage
  could represent the same building at their shared boundary. Establish a
  single stable identity and its frontages explicitly; do not silently create
  two taverns or infer that one has entrances onto both spaces.
- Proposed connecting statement for later source verification/authoring:
  "The village square lies east of the market. The tavern stands at their
  shared boundary. Open pedestrian access connects the two spaces. A path
  leaves the square northeast toward the church."
  This is an illustrative proposal, not verified module geography; pedestrian
  access, tavern identity and the church route remain to be established.
- Sharing a schematic cell establishes a broad position, not an exact
  distance, line of sight, audibility, doorway or unobstructed route. Represent
  those separately when an action or rule depends on them. Do not derive
  mechanical legality or Firelight statistics from grid appearance alone.
- Planning follow-up: evaluate narrator-facing scene/route relationships
  first, then render knowledge-filtered player views from the same canonical
  model. Carry this priority into the SP4 decision report and subsequent S2,
  S3, S4 and regional planning, without silently changing approved scope,
  preregistration thresholds or ADR status.

## Owner example: Builder-authored village tavern (AB03 review)

- Original #10 rated 1/3. This rating applies only to the original empty-grid
  artifact, not the illustrative replacement below.
- Owner requests Module Builder authority to populate rich initial scenes
  using public seed narrative fragments, rather than merely extracting sparse
  positions from existing prose. Record this as a planning direction for
  Builder/TITAN integration, not permission to run the production seed job,
  mutate published modules, or change frozen pilot evidence. Source licensing,
  provenance, approved seed contracts and schema sign-off still apply.
- Proposed initial authored map, north up, schematic and not to scale:
  - NW: bar counter and stools.
  - N: bar counter and stools, town ruffian on a stool, staff-only exit
    proposed toward stores/kitchen; exact destination(s) and connectivity
    remain to be authored, with no additional room inferred.
  - NE: table and patrons, town madame, trophies along the wall.
  - W: bar counter and stools, barmaid's working position.
  - C: table with gamblers; preserve a circulation route through the room.
  - E: hearth with a raging fire, trophies on the wall above the hearth.
  - SW: no additional placement specified by the owner.
  - S: front door, half-orc bouncer beside it.
  - SE: tables and patrons, trophies along the wall.
- Identify any named NPC by its canonical name/ID when established; the owner
  supplied roles here, not personal names. Do not fabricate names as if they
  came from the module. Roles and initial positions should be linked to
  stable entities rather than embedded only in decorative prose.
- Distinguish initial NPC positions from permanently fixed anchors: the bar,
  hearth and doors stay fixed, while NPCs can move through canonical updates.
- Suggested LLM-facing additions (assistant proposals, not owner decisions):
  explicitly record counter shape and staff/customer sides, paths between
  entrances and tables, door destination/state, and which facts are public
  versus GM-only. Keep compass orientation consistent with the external
  square; the proposed S-facing door does not yet establish which external
  space it opens onto. Do not infer tactical distances, cover, line of sight,
  fire damage, or access permissions from cell membership alone.
- Rich narration may elaborate mood and incidental detail without relocating
  committed anchors or silently creating persistent rooms/NPCs/routes. New
  actionable facts require the approved authoring/runtime state boundary.

### Tavern example: narrator-facing relationship description

The entrance opens from the south, with the half-orc bouncer stationed beside
it. The bar occupies the western and northwestern sides and continues along
the north; the barmaid works behind it, while the town ruffian sits at its
northern section. Gamblers occupy the central table, and the town madame sits
northeast. A raging fire dominates the eastern hearth beneath the trophies.
More tables fill the southeast. A staff exit lies behind the northern bar;
its destination must be established during authoring.

This is the owner-guided illustrative replacement, not extracted module truth.
Make initial relationships explicit alongside cell labels: "behind the
counter", "beside the entrance", "above the hearth", and a proposed clear
circulation route around the gambling table. Preserve fixed anchors separately
from mobile occupants. Do not assign NPC names absent a canonical identity.

## Handoff to the S mapping goal

Owner correction: this feedback is addressed to S (mapping), not N (Network).
S planners/builders must read these examples alongside the original-artifact
scores when preparing the SP4 handoff and subsequent spatial/Builder plans.
The owner feedback is still accumulating; no final aggregate verdict, schema
choice, ADR acceptance or runtime implementation is authorized by these notes.

Original-artifact score snapshot (legibility/usefulness, guided-review numbers):

| Review # | Artifact | Score |
| --- | --- | --- |
| 1 | Fixture interior tavern | 5/5 |
| 2 | Fixture village green | 5/4 |
| 3 | Fixture tower approach | 5/4 |
| 4 | Fixture combat tavern P1 | 5/5 |
| 5 | Fixture combat tavern P4 | 5/5 |
| 6 | Keep of Doom AA01 trailhead | 3/3 |
| 7 | Keep of Doom AL01 causeway | 2/3 |
| 8 | Pumpkin King's Curse AB01 market | 2/2 |
| 9 | Pumpkin King's Curse AB02 village square | 1/1 |
| 10 | Pumpkin King's Curse AB03 tavern | 1/3 |
| 11 | Pumpkin King's Curse AD01 corn arena (revised) | 3/3 |

Review #12-16 remain unrated. The owner's separate 5/5 for the redesigned
village square is feedback on that new example and must not enter the M1
original-artifact mean. CSV sketch IDs, not conversational ordering, are the
canonical score bindings. This table is a dated-in-conversation handoff
snapshot; later owner revisions belong in the CSV and appended notes.

## Owner example: crossroads V01 (#12)

- Original #12 rated 1/2. The owner finds "Four Ancient Footpaths" placed
  only in C confusing and next to useless for directionality.
- Owner-proposed redesign: one junction in C with four route arms extending
  N/E/S/W. Lichen-covered low stone walls converge toward the junction;
  sunken pedestals, markers and lanterns characterize the crossing. Paths
  occupy multiple cells rather than being treated as a point object in C.
- Owner authorizes an illustrative extrapolation of blighted cornfields in
  NW/NE/SW/SE. This and the cardinal path orientation are example authoring
  choices, not verified extracted facts. Do not replace the original artifact
  or its 1/2 score, mutate the module, or claim these as pilot observations.

```text
NW: blighted cornfield | N: northbound path | NE: blighted cornfield
W: westbound path     | C: crossroads      | E: eastbound path
SW: blighted cornfield| S: southbound path | SE: blighted cornfield
```

### Proposed narrator-facing relationship description

Four path arms meet at a single central crossroads. The north-south route
intersects the east-west route; these are four directions from one junction,
not four independent paths confined to its centre. Blighted cornfields occupy
the four corners between the arms. Lichen-covered low stone walls follow the
field edges toward the crossing, framing the paths without closing them.
Sunken lantern pedestals and weathered markers cluster at the junction's
margins, leaving the crossing itself passable; dust lies across the paths.

The path-edge walls, passable centre and marker positions in this prose are
assistant-proposed authoring details, not verified module data. Establish
route destinations and any restrictions separately; do not infer every arm
is safe, its destination known, or passage through the fields impossible.
Keep lantern presence separate from whether lanterns are lit. Describe
atmosphere freely without changing the committed junction topology.

Planning implication: represent route arms, their connections and boundary
relationships explicitly in the canonical model. Derive both the sketch and
the LLM packet from those facts. A central feature label alone is insufficient
to communicate traversable topology. Do not infer mechanical distances,
visibility through corn or cover from this schematic.

Rating progress update: #12 now 1/2; #13-16 remain unrated.

## Owner clarification: Builder is a creator, not an extractor or narrator

- For the redesigned examples, the owner explicitly asks the assistant to act
  as Module Builder with creative authoring authority: establish geography,
  populate scenes and embellish descriptions using world narrative seed
  fragments. Do not constrain this design exercise to facts extractable from
  the sparse legacy text or repeatedly disclaim every proposed placement.
- These are authored initial-world decisions, not claims that old module text
  already contained them. Once a Builder result is validated and published,
  its geography becomes canonical module reality for runtime narration.
- Distinguish three modes: extraction faithfully reports existing facts;
  Builder authoring creates and commits new initial facts; runtime narration
  elaborates within committed facts and the approved state-mutation boundary.
- Builder freedom should resolve previously open positions and route
  relationships into coherent scene and adventure topology, with stable IDs,
  reciprocal scene connections and appropriate knowledge filtering. Validation
  checks consistency, not whether every new authored detail appeared verbatim
  in its seed fragment.
- This review conversation has not actually supplied or loaded the world seed
  corpus; examples must not claim fragment provenance that was not consulted.
  Actual corpus ingestion, production seed generation and module publication
  retain their existing approvals, validation and persistence requirements.
- Current action: continue authoring concrete replacement examples in the
  feedback notes. Original pilot artifacts and their ratings stay unchanged;
  no published module files were edited by this clarification.
- Subsequent owner clarification: Builder creativity remains constrained by
  Python-owned reality and larger-grid topology. Seed-derived embellishment
  should clothe that structure, not invent incompatible connections. Detailed
  Builder enforcement is future work, not a requirement to implement during
  this review.

## Builder-mode example: scarecrow hollow V02 (#13)

- Original #13 rated 1/2. Owner asks Builder to choose the grid's scope,
  explain whether the perimeter occupies outer cells or borders them, and
  populate the scene rather than listing unplaced features.
- Authored example scope: the whole hollow and its immediate rim. The sunken
  ground spans all nine cells; C is its deepest point, not the only sunken
  space. No mechanical cell size or measured distances are specified.
- Rotten fence posts follow the outside boundary of the eight perimeter
  cells. Ward-faced posts stand along the inner rim within those cells,
  facing the central Great Scarecrow; do not accidentally imply two nested
  solid fences. Both are discontinuous posts, not proven impassable walls.
- C: Great Scarecrow in the deepest churned ground, oily dust on its straw,
  bones and faded ribbon around its base. N/NE/NW: inward-facing ward posts
  over sloping churned ground. E/W: rim posts above muddy lateral slopes.
  SE/SW: bones and ribbon caught in churned ground below leaning perimeter
  posts. S: inward-facing ward post and a visible muddy descent from the rim.
- The southern descent is local scene staging, not a new external route or
  connection to another location. Existing Python-owned entry/exit topology
  remains authoritative; rotate or adapt the staging to its actual approach.
- Narrator relationships: posts encircle the hollow, ground slopes inward,
  central scarecrow dominates the depression, rimward ward faces point inward.
  Surface dressing may vary without moving these anchors. No sightline,
  movement cost, combat radius or damage value is inferred from the drawing.

## Assistant design assessment: original versus redesigned hollow

- Owner's numeric rating of the ORIGINAL V02 artifact: legibility 1,
  usefulness 2. This remains the only V02 rating in the M1 CSV.
- Owner's qualitative response to the REDESIGN: "Brilliant! Now that's a
  scene I can envision navigating"; the owner regards it as more realistic.
  No owner numeric rating of the redesign has been supplied.
- Assistant's separate assessment of its OWN REDESIGN: legibility 4/5,
  usefulness 5/5. This is not a blinded or independent evaluation and must
  never be substituted into the owner CSV, the original M1 mean, or a live
  gate verdict. No assistant numeric rating of the original was elicited.

### Why the redesign is more useful to an LLM

1. Explicit scope: the drawing covers one hollow and its immediate rim, not
   an unspecified chunk of countryside. Grid cells do not imply equal-sized
   tactical squares or measured travel distances.
2. Coherent terrain: the sunken ground spans multiple cells, with C as its
   deepest point. The model can describe descending or moving along the rim
   without treating every noncentral cell as outside the scene.
3. Clear boundaries: rotten posts mark the outer perimeter; ward-faced posts
   face inward. A broken sequence of posts is not silently upgraded into an
   impassable solid fence by the drawn border.
4. Stable anchor relationships: the scarecrow dominates C; slopes lead inward;
   ward faces look toward it; bones and ribbon lie on the lower slopes and at
   its feet. The scene is more than a central object plus unplaced scenery.
5. Navigable mental model: the narrator has enough structure to describe an
   approach, descent or rimward movement while preserving landmark positions.
   Actual entry/exit links and mechanical legality still come from canonical
   topology and appropriate rules data, not the schematic.
6. Narrative affordances: gourd face, runes, oily straw, ribbons and bones
   support vivid prose without needing to move the committed terrain or
   invent incompatible geography.

### Why legibility is 4 rather than 5

The rendered example is crowded and has a split-word typo ("run es"). The
concept is clear, but a cleaner label layout and an explicit legend for the
non-solid border would improve readability. Preserve that limitation when
reporting the assessment; do not present the drawing as flawless.

## Future use of owner-calibrated LLM design assessment

The owner explicitly values the LLM's design assessment and proposes refining
it through this guided review for use in future runs. Preserve the paired
originals/redesigns, exact owner ratings/comments, assistant assessments and
subsequent owner corrections as calibration examples for S's planning handoff.
This is feedback-guided evaluation practice, not a claim that model weights
were trained or that a future session automatically inherits this judgment.

Suggested future evaluation criteria, distilled from the owner-guided examples:

- Does the map declare scope and orientation, including uncertain directions?
- Does it preserve larger-grid connections and stable cross-scene identities?
- Are paths, slopes and boundaries represented across the cells they occupy?
- Are meaningful relative positions explicit, rather than stranded in prose?
- Can an LLM describe movement without relocating landmarks or inventing exits?
- Are fixed anchors distinguished from initial mobile occupants?
- Can the narrator enrich atmosphere without changing canonical spatial facts?
- Are unknown distances, sightlines, access and mechanical values kept unknown?
- Is the grid itself informative, or is all useful information in the prose?

For later runs, label every score by assessor and artifact/version. Have an
LLM assess before seeing owner scores when measuring agreement; distinguish
drafting/self-review from an independent assessment. Compare with held-out
owner judgments and real narration/navigation outcomes before relying on an
automated surrogate. Any proposal to replace required human ratings or change
frozen pilot thresholds needs explicit approval; this feedback grants neither.

Planning handoff to S: carry these findings, examples and limitations into
SP4/Builder/spatial evaluation design alongside the original scores. Do not
turn the assistant's preference into a proven contradiction reduction or an
implemented gameplay capability.

## Appendix: expanded ASCII scene examples

These drawings collect the owner-guided replacement examples from the review.
They are design/Builder-authoring examples, not replacements for the frozen M1
artifacts or their scores. Builder decisions must remain compatible with
Python-owned larger-grid topology. North is up; scale is schematic, not a
fixed movement distance. Original scores and separate example assessments
remain distinguished in the notes above.

### A. Causeway: a path spanning cells

The proposed north-south orientation is an authoring choice to reconcile with
the adventure route graph, not an extracted compass fact. Pillars, guard posts
and processions still need explicit placement if they matter to navigation.

```text
+-----------------------+-----------------------+-----------------------+
| NW                    | N                     | NE                    |
| Marsh                 | Broken causeway       | Marsh                 |
|                       |          |            |                       |
+-----------------------+----------|------------+-----------------------+
| W                     | C        |            | E                     |
| Marsh                 | Broken causeway       | Marsh                 |
|                       |          |            |                       |
+-----------------------+----------|------------+-----------------------+
| SW                    | S        |            | SE                    |
| Marsh                 | Broken causeway       | Marsh                 |
+-----------------------+-----------------------+-----------------------+
```

### B. Village market: stalls inside a field boundary

The fences bound stalls and market space; they do not fill the entire outer
cells. The scarecrow is beyond the northwestern fence, watching the market.
Village buildings lie to the east. The tavern frontage is illustrative and
must share one identity with its frontage in the adjoining square if adopted.

```text
+-----------------------+-----------------------+-----------------------+
| NW                    | N                     | NE                    |
| Field fence           | Field fence           | Village housing       |
| Stall inside fence    | Stall inside fence    | Vendor stall in front |
| Scarecrow beyond      | Fields beyond         |                       |
+-----------------------+-----------------------+-----------------------+
| W                     | C                     | E                     |
| Field fence           | Open market square    | Tavern frontage       |
| Stall inside fence    | Display tables        | Vendor stall in front |
| Fields beyond         | Mayor? Unconfirmed    |                       |
+-----------------------+-----------------------+-----------------------+
| SW                    | S                     | SE                    |
| Field fence           | Not yet specified     | Village housing       |
| Stall inside fence    |                       | Vendor stall in front |
| Fields beyond         |                       |                       |
+-----------------------+-----------------------+-----------------------+
```

### C. Village square: open space extends to the frontages

Market stalls are west, as corrected by the owner. The church path exits NE;
the church itself is beyond this scene. The possible incline remains an
uncertain recollection. A shared tavern at the market/square boundary and
pedestrian passage between scenes must be established explicitly.

```text
+-----------------------+-----------------------+-----------------------+
| NW                    | N                     | NE                    |
| Village buildings     | Village buildings     | Village buildings     |
| Market-side stalls    | Lanterns at frontage  | Lantern at frontage   |
| Lantern; square space | Square space          | Path toward church -> |
+-----------------------+-----------------------+-----------------------+
| W                     | C                     | E                     |
| Tavern frontage       | Open cobbled square   | Village buildings     |
| Market-side stalls    | Space to gather       | Lanterns at frontage  |
| Lantern; square space |                       | Square space          |
| <- Adjacent market    |                       |                       |
+-----------------------+-----------------------+-----------------------+
| SW                    | S                     | SE                    |
| Village buildings     | Village buildings     | Village buildings     |
| Market-side stalls    | Lanterns at frontage  | Lanterns at frontage  |
| Lantern; square space | Square space          | Square space          |
+-----------------------+-----------------------+-----------------------+
```

### D. Village tavern: populated initial scene

NPC labels are roles until linked to canonical names/IDs. The southern door
must be reconciled with the external scene; the northern staff exit's exact
destination remains to be authored. The grid does not create extra rooms or
entrances. The counter spans W/NW/N, with staff behind and stools on its
public side; occupants can move while anchors remain fixed.

```text
                 Staff exit -> stores/kitchen?
                 Destination to be established
+-----------------------+-----------------------+-----------------------+
| NW                    | N                     | NE                    |
| BAR COUNTER           | BAR COUNTER           | Table and patrons     |
| Stools on public side | Stools; town ruffian   | Town madame at table  |
|                       | Staff exit behind bar | Trophies on wall      |
+-----------------------+-----------------------+-----------------------+
| W                     | C                     | E                     |
| BAR COUNTER           | Gambling table        | HEARTH: RAGING FIRE   |
| Stools on public side | Gamblers gathered     | Trophies above hearth |
| Barmaid behind bar    | Circulation space     | and along wall        |
+-----------------------+-----------------------+-----------------------+
| SW                    | S                     | SE                    |
| Not yet furnished     | FRONT DOOR            | Tables and patrons    |
|                       | Half-orc bouncer      | Trophies along wall   |
|                       | beside entrance       |                       |
+-----------------------+-----------------------+-----------------------+
```

### E. Crossroads: one junction, four route arms

Cornfields occupy the corners between the arms. Low stone field boundaries
converge toward the crossing; markers and lantern pedestals frame its margins.
Route destinations and lantern illumination are separate facts to establish.

```text
+-----------------------+-----------------------+-----------------------+
| NW                    | N                     | NE                    |
| Blighted cornfield    | Northbound path       | Blighted cornfield    |
| Low stone boundary    | Between field edges   | Low stone boundary    |
|                       |           |           |                       |
+-----------------------+-----------|-----------+-----------------------+
| W                     | C         |           | E                     |
| Westbound path -------+-- CENTRAL CROSSROADS -+--- Eastbound path      |
|                       | Weathered markers     |                       |
|                       | Lanterns / pedestals  |                       |
+-----------------------+-----------|-----------+-----------------------+
| SW                    | S         |           | SE                    |
| Blighted cornfield    | Southbound path       | Blighted cornfield    |
| Low stone boundary    | Between field edges   | Low stone boundary    |
+-----------------------+-----------------------+-----------------------+
```

### F. Scarecrow hollow: terrain, rim and central anchor

The hollow and its immediate rim fill this view. Sunken ground spans the
whole grid; C is deepest. The outer border below denotes scattered rotten
posts, NOT a continuous or impassable wall. Ward faces point inward. The
southern descent is local staging, not a new inter-scene connection.
This collected version fixes the earlier split-word "run es" typo.

```text
          SCATTERED ROTTEN POSTS AT OUTER BOUNDARY
+-----------------------+-----------------------+-----------------------+
| NW                    | N                     | NE                    |
| Leaning posts         | Ward-faced post       | Leaning posts         |
| Ward face toward C    | Facing south toward C | Ward face toward C    |
| Ground slopes inward  | Muddy slope           | Ground slopes inward  |
+-----------------------+-----------------------+-----------------------+
| W                     | C                     | E                     |
| Rim ward face ->      | GREAT SCARECROW       | <- Rim ward face      |
| Muddy slope           | Gourd face and runes  | Muddy slope           |
| Ribbon in mud         | Deep churned mud      | Scattered bones       |
|                       | Bones at its feet     |                       |
+-----------------------+-----------------------+-----------------------+
| SW                    | S                     | SE                    |
| Leaning posts         | Ward face toward C    | Leaning posts         |
| Bones and ribbon      | Muddy descent         | Bones and ribbon      |
| Ground slopes inward  | from rim              | Ground slopes inward  |
+-----------------------+-----------------------+-----------------------+
```

Assistant assessment 4/5 legibility and 5/5 usefulness refers to the earlier
displayed hollow redesign, not a new assessment of this tidied appendix
version. The owner's 1/2 remains attached to the original V02 pilot artifact.

### G. Cave threshold: forest-to-cavern mise-en-scene (NC01, review #14)

Original #14 rated 1/1. Owner-established context: the party approaches from a
blighted, corrupted forest under stormy skies; the cliff cannot be bypassed,
and forward progress requires entering the cave. Retreat along the approach
is distinct from a route around the cliff. Owner asks for the cave mouth in
C and a foreboding transition into the adventure's dark cave section.

Builder example: north up, approach from S, cliff across E/W, cave mouth in C.
The view spans the final forest approach, cliff frontage and immediate cave
threshold, not the whole cave system. Placement is an initial authoring
choice to reconcile with canonical larger-grid orientation before publishing.

```text
+-----------------------+-----------------------+-----------------------+
| NW                    | N                     | NE                    |
| Cliff mass            | First dark passage    | Cliff mass            |
| Water down limestone  | Faint fungi on stone  | Wet limestone         |
| No bypass             | Whisper from within   | No bypass             |
+-----------------------+-----------------------+-----------------------+
| W                     | C                     | E                     |
| Sheer cliff frontage  | CAVE MOUTH / THRESHOLD | Sheer cliff frontage  |
| Slick rock; roots     | Forest light fades    | Slick rock; seepage   |
| No lateral route      | Water-darkened floor  | No lateral route      |
+-----------------------+-----------------------+-----------------------+
| SW                    | S                     | SE                    |
| Blighted trees        | Corrupted forest path | Blighted trees        |
| Twisted roots         | Approach / retreat    | Twisted roots         |
| Storm-exposed ground  | Storm-exposed ground  | Storm-exposed ground  |
+-----------------------+-----------------------+-----------------------+
```

#### Builder-authored scene description

The forest path ends against a wall of rain-black limestone. Blighted trunks
crowd its foot, their roots caught in the rock like fingers that have lost
their grip. Neither flank offers a way around the cliff. At the centre, a
low, uneven mouth opens into the stone; rainwater threads down its lip and
crosses the threshold in thin, dark rivulets.

Behind the party, thunder rolls over the corrupted canopy. Within the mouth,
the grey daylight dwindles into a faint phosphorescent bloom along the wet
walls and floor. The first passage bends out of sight. A whisper seems to
travel outward with the cold air, too indistinct to resolve into words.
The storm remains behind; the deeper darkness begins here.

The prose embellishes supplied cave features and owner context; no actual
narrative seed fragments were accessed, and no fragment provenance is claimed.
This example establishes no secret passage, extra exit, named speaker or
mechanical property of the whisper/fungi. The passage's obscured continuation
does not disclose the deeper cave layout.

#### Mise-en-scene as a Builder planning principle

Owner proposes this concept for the Module Builder system prompt. Stage a
scene as a coherent spatial and sensory arrangement serving its adventure
role: the approach, threshold, visible focal point, surrounding boundaries,
actionable routes, light/sound/weather gradients, and transition to the next
section. Enrich Python-owned topology rather than silently creating new
connections. Distinguish visible cues from hidden explanations and mechanical
effects. NPC/prop/terrain placement should support possible player action,
not merely decorative lists. This is planning feedback, not a prompt edit or
authorization to change current runtime behavior.

Rating progress update: #14 now 1/1; #15-16 remain unrated.

## IMPORTANT owner development: mise-en-scene is the mapping goal

The owner explicitly identifies mise-en-scene as the mapping goal, with
significant implications for Module Builder, TITAN and the Narrator in
different ways. This is a central planning finding, not a minor rendering
preference. The cave-threshold grid and complete scene description are
preserved in Appendix G above as the concrete worked example; the other
expanded examples remain in Appendices A-F.

The desired result is an actionable, coherent imagined scene: approach,
threshold, spatial boundaries, focal points, terrain, inhabitants, sensory
relationships and links to the wider adventure. The grid is a compact
representation of that arrangement, not the goal by itself. A diagram with
mostly empty cells and a disconnected feature list can validate structurally
while failing this experience goal.

### Distinct cross-track planning implications

- **Module Builder:** stage initial module reality. Use approved narrative
  seed material to enrich the fixed topology with coherent places, anchors,
  initial occupants, approaches, thresholds and sensory cues. Persist explicit
  relationships after validation. Builder creates the initial arrangement;
  it does not merely extract the sparse facts of legacy descriptions.
- **TITAN:** consider how approved world/region context supplies the wider
  relationships that make a local scene intelligible: routes, landscape,
  settlement placement, weather and consequences, through its owning
  contracts. A local grid must not invent connections that conflict with
  those relationships. This feedback does not move module-local authoring
  ownership into TITAN or authorize its production seed job.
- **Narrator:** turn the committed arrangement into a vivid, responsive
  player experience. Describe approaches, transitions, atmosphere and
  interactions naturally while maintaining landmarks, route continuity,
  actor positions and character-knowledge boundaries. Use the spatial model
  without reciting its cells, predetermining choices or relocating facts.
- **Player map:** provide a secondary, cumulative, knowledge-filtered view of
  the same arrangement to aid shared planning. Map polish is not a substitute
  for spatially coherent narration.

### Required planning handoff

S must highlight this IMPORTANT owner finding in its SP4 handoff, with the
worked examples and their separate original-artifact ratings, for the owners
of spatial, Builder, TITAN and Narrator planning. Review their existing
contracts and identify any concrete plan/spec/ADR changes needed; do not
silently expand an active change or duplicate canonical state owners.

Evaluation should examine whether the supplied representation lets an LLM
stage a scene and sustain spatial continuity under player action, not merely
whether it can draw or parse a grid. Retain owner feedback, assistant
self-review and actual runtime outcomes as separate evidence classes.
No rating waiver, ADR acceptance, gate PASS or runtime implementation is
implied by this planning development.

### Appendix H. Abandoned research camp: investigation mise-en-scene

Original #15 (Thornwood Watch NC04) rated 1/2. Owner reports having visited
the scene with Acheron, Kira and companions and considers the original central
fire-pit label plus unplaced list likely to invite spatial invention and
player confusion. Owner asks Builder to stage the clearing within surrounding
forest and make investigating tents and camp objects spatially coherent.

Scope: the entire forest clearing and its wooded boundary, not the wider
forest. North up, schematic, no measured cell size. Initial placements below
are Builder example choices; the southern approach must align with the
canonical entry and does not authorize a new external connection.

```text
                 FOREST AROUND THE CLEARING
+-----------------------+-----------------------+-----------------------+
| NW                    | N                     | NE                    |
| Forest behind tent    | Forest boundary       | Forest behind tent    |
| Torn research tent    | Corruption seep       | Torn sleeping tent    |
| Equipment; loose notes| Clearing ground inside| Scattered bedding     |
+-----------------------+-----------------------+-----------------------+
| W                     | C                     | E                     |
| Forest boundary       | COLD FIRE PIT         | Forest boundary       |
| Collapsed supply tent | Ashes; blackened stones| Corruption pools     |
| Abandoned equipment   | Open gathering space  | Muddy clearing edge   |
+-----------------------+-----------------------+-----------------------+
| SW                    | S                     | SE                    |
| Forest boundary       | Camp approach         | Forest boundary       |
| Corruption seep       | Open way to fire pit  | Tent ropes and stakes |
| Clearing ground inside| Passage among tents   | Clearing ground inside|
+-----------------------+-----------------------+-----------------------+
```

#### Player-facing arrival description

The trees draw back around a clearing, though their branches still crowd its
edges. A cold fire pit occupies the centre: blackened stones around a bed of
grey ash, with trampled ground where the camp once gathered.

Beyond it, a research tent sags against the northwestern tree line. Torn
papers lie among abandoned equipment outside its entrance. A second tent
slumps to the northeast, its split canvas exposing scattered bedding. On the
western side a collapsed supply tent has spilled its contents toward the
open ground. Dark seepage gathers at the northern, eastern and southwestern
edges, soaking the soil beneath the trees. Fallen ropes and stakes snag the
grass southeast of the pit.

The approach leaves a clear way toward the central stones. From there, the
tents and their scattered contents invite closer examination.

#### Builder/GM-only trigger and knowledge boundary

Owner-established fact: the cold fire pit has a surprise, but only if the
party attempts to start a fire. Preserve the module's actual trigger and
effect in its canonical authored data; its nature was not supplied here and
must not be invented. Initial arrival prose and the public map must not
reveal the surprise or activate it merely because the party arrives, looks
at ash or investigates tents. Those actions may disclose other authored
clues, but do not substitute for the specified fire-lighting attempt.

"Whisper Ashes" is the original feature label. The public example uses plain
"ashes" rather than implying an audible supernatural event before the
module's actual perceptibility/trigger rules permit it. Public maps and
narrator inputs need distinct knowledge treatment; a GM-aware narrator may
receive the guarded trigger while player-visible projections omit it.

#### LLM-facing arrangement and authoring caveats

Forest forms the perimeter; outer cells also contain usable clearing space.
The fire pit is fixed at C; research, sleeping and supply tents are distinct
stable anchors at NW, NE and W. Notes are related to equipment at NW, bedding
to the NE tent, and pools to the clearing edge rather than all being piled at
C. Movement descriptions can use these relationships without relocating
objects. Distinct tent roles, bedding, ropes and stakes are example authoring
embellishments, not extracted legacy facts. Entry/exit topology, accessibility,
pool effects, cover and distances remain governed by canonical data.

Do not place Acheron, Kira or any PC initially just because they visited in a
previous playthrough. Current party/actor positions come from runtime state.

Rating progress update: #15 now 1/2; #16 remains unrated.

### Appendix I. Voidstone hilltop: climactic mise-en-scene (NC05, #16)

Owner rating of ORIGINAL #16: 1/1. Owner separately rates the expanded example
below 5/5. Only the original 1/1 enters the M1 CSV and its aggregate; the
replacement 5/5 is owner feedback on a newly authored design example.

The owner identifies this as one of The Thornwood Watch's climactic scenes.
The original shows a central focal point but does not locate the stone circle
or trees, extend channels across cells, or distinguish the distortion's extent
from the altar's position. It provides a feature inventory, not scene staging.

Scope: summit clearing and enclosing stone/tree ring. North up, schematic,
not measured tactical squares. The southern approach in this example must
connect to the adventure's established route, not create an incompatible exit.

```text
+-----------------------+-----------------------+-----------------------+
| NW                    | N                     | NE                    |
| Twisted sentinel tree | Standing stones       | Twisted sentinel tree |
| Leaning circle-stone  | Channel reaches rim   | Leaning circle-stone  |
| Channel branches NW   | Channel northward     | Channel branches NE   |
+-----------------------+-----------------------+-----------------------+
| W                     | C                     | E                     |
| Trees behind western  | VOIDSTONE ALTAR       | Trees behind eastern  |
| circle-stones         | Distortion near stone | circle-stones         |
| Channel westward      | Channels radiate out  | Channel eastward      |
| Bare summit ground    |                       | Bare summit ground    |
+-----------------------+-----------------------+-----------------------+
| SW                    | S                     | SE                    |
| Twisted sentinel tree | Gap between stones    | Twisted sentinel tree |
| Southern circle-stone | Established approach  | Southern circle-stone |
| Channel branches SW   | Altar visible ahead   | Channel branches SE   |
+-----------------------+-----------------------+-----------------------+
```

#### Builder-authored arrival description

The ascent breaks onto a bare summit enclosed by weathered standing stones.
Beyond them, twisted sentinel trees rise like crooked spires, their branches
reaching over the circle without meeting.

At its centre stands the Voidstone altar. Channels divide the ground around
its base, spreading outward between the stones and beneath the roots of the
enclosing trees. From the approach, their lines draw the eye inward toward
the stone.

The air immediately around the altar distorts its edges. Looking past it,
the far side of the circle seems briefly displaced, then settles when the
gaze shifts. The summit offers room to move around the altar, but the channels
interrupt every approach to its base.

#### Narrator-facing design findings

- Readable hierarchy: approach -> enclosing ring -> central altar.
- Connected features: channels link the centre to the perimeter; trees stand
  beyond the stones, rather than all anchors being collapsed into C.
- Space for player action: investigate the rim, move around the circle or
  approach the altar, without predetermining a choice or successful outcome.
- Explicit initial extent: the proposed visual distortion is near the
  Voidstone, not an unspecified effect everywhere on the summit.
- Atmospheric menace does not establish damage, difficult terrain, magical
  conditions, enemies or ritual triggers. Those must follow module/rules
  data. The staging and prose above are Builder-authoring choices for later
  validation, not proof those details existed in legacy source.

M1 review now complete: all 16 ORIGINAL artifacts have owner scores. Keep the
separate 5/5 owner ratings for expanded village square and Voidstone hilltop
examples out of the original-artifact aggregate. D1 claim audit, transcript
ratings, format/combat/data choices and ADR-0034 acceptance are not completed
by finishing M1.

## Final M1 owner-score record and prospective planning direction

This section supersedes the earlier in-progress rating snapshots, without
rewriting the review history. The owner completed the review and explicitly
directed that its mise-en-scene lessons be embedded in the mapping goal and
future pilot planning. The approved next step is a prospective planning
follow-up, not rewriting the completed experiment or reopening SP3b.

Source: S worktree `m1/m1-20261105-02/ratings.csv`, beneath
`tmp/router-rollout/mapping-pilot/`. SHA-256 of the completed CSV:
`2611bc239076fc5e7d47f2495576134369e24f823049f45cd1c11da09f1b3b78`.
All values below are owner judgments of ORIGINAL artifacts, recorded during
the guided review; redesigned examples and assistant self-assessments are
excluded. Review numbers are conversational labels, not CSV row order.

| Review # | Original artifact | Legibility | Usefulness |
| --- | --- | ---: | ---: |
| 1 | Fixture interior tavern | 5 | 5 |
| 2 | Fixture landscape village green | 5 | 4 |
| 3 | Fixture tower approach | 5 | 4 |
| 4 | Fixture combat tavern P1 | 5 | 5 |
| 5 | Fixture combat tavern P4 | 5 | 5 |
| 6 | Keep of Doom AA01 trailhead | 3 | 3 |
| 7 | Keep of Doom AL01 causeway | 2 | 3 |
| 8 | Pumpkin King's Curse AB01 market | 2 | 2 |
| 9 | Pumpkin King's Curse AB02 village square | 1 | 1 |
| 10 | Pumpkin King's Curse AB03 tavern | 1 | 3 |
| 11 | Pumpkin King's Curse AD01 corn arena (revised) | 3 | 3 |
| 12 | Pumpkin King's Curse V01 crossroads | 1 | 2 |
| 13 | Pumpkin King's Curse V02 scarecrow hollow | 1 | 2 |
| 14 | Thornwood Watch NC01 cave threshold | 1 | 1 |
| 15 | Thornwood Watch NC04 abandoned camp | 1 | 2 |
| 16 | Thornwood Watch NC05 Voidstone hilltop | 1 | 1 |

| Descriptive group | Count | Legibility mean | Usefulness mean |
| --- | ---: | ---: | ---: |
| Entire original M1 packet | 16 | 2.625 | 2.875 |
| Authored fixtures | 5 | 5.000 | 4.600 |
| D1-generated locations | 11 | 1.545 | 2.091 |
| Combat fixtures (subset of authored fixtures) | 2 | 5.000 | 5.000 |

The whole packet misses the frozen 3.5 threshold on both axes. The descriptive
subgroups explain the contrast but do not replace that aggregate criterion,
establish a live combat PASS, or prove the redesigns improve narration.
The owner rated the expanded square and Voidstone examples 5/5 separately;
these are development feedback, not new samples in the original packet.

### Lessons to embed prospectively

1. Narrator-first mise-en-scene: the representation must stage an actionable,
   coherent place; player maps are a secondary projection of those facts.
2. Data quality before cosmetic rendering: reject a valid-but-empty diagram
   as sufficient evidence of positional coverage. Distinguish absent authored
   information from renderer failure; preserve unknowns rather than fabricate
   extraction facts.
3. Builder mode can author coherent new initial facts under Python-owned
   topology, using approved seed material with provenance. Extraction and
   runtime narration have different authority and must remain distinct.
4. Scene scope, schematic scale, orientation, spanning paths/boundaries and
   relative placements must be explicit. Stable identities and reciprocal
   links preserve continuity between scene and wider-region views.
5. Stage approaches, thresholds, focal points, usable space and initial
   occupants; separate fixed anchors from moving actors. Sensory cues and
   hidden triggers need knowledge-appropriate treatment (camp Appendix H).
6. Validate graph/identity compatibility and actionable mechanical facts
   without trying to model every descriptive detail deterministically.
7. Use Appendices A-I as owner-guided teaching/design examples, not hidden
   answer keys for a claimed independent test. Future evaluation should use
   separately declared held-out scenes and multi-turn navigation tasks.
8. Keep owner ratings, assistant self-review and actual runtime outcomes
   separate. Automated assessment remains advisory until calibrated against
   held-out owner judgments; it cannot silently replace required human gates.

### S follow-up deliverable

S is authorized to resume provider-free planning work: append the completed
M1 result and feedback provenance to its SP4 report, and publish a proposal
for a new mise-en-scene authoring/projection/evaluation follow-up. Map the
contracts and ownership across Spatial S1-S5/SC, Builder, TITAN, Narrator,
Network and Firelight; identify what can be evaluated offline and what later
needs separately authorized live evidence. The proposal must reference these
worked examples and specify acceptance checks that actually test scene
relationships and continuity rather than just schema validity.

Do not implement a schema, prompt or runtime change yet. Do not reopen SP3b,
spend its unused budget, alter the frozen pilot inputs/thresholds, republish a
module, accept ADR-0034, or complete missing owner inputs. D1 audit, rateable
transcript judgments and unresolved final owner choices remain explicitly
pending. Submit the planning PR for Overseer review before implementation.
