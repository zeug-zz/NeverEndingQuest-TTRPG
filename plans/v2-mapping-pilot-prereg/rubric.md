# V2 Mapping Pilot Owner Rubric

Status: proposed anchors for SP0 owner ratification; no ratings assigned.

Score each dimension independently from 1 to 5. Scores 2 and 4 interpolate
between the written anchors for 1, 3 and 5. Cite a short transcript quote or
explanation for every score. Do not replace factual scoring with subjective
ratings, and do not let vivid prose excuse a spatial error. Score only content
available in the row; use `not rateable` for a missing/truncated response and
do not impute a value.

## Dimensions and anchors

### 1. Sense of place

- **1:** No coherent external place is established, or spatial statements
  contradict the supplied scene.
- **3:** The scene is understandable and mostly stable, with limited
  specificity; it feels like a location but not a persistent, distinctive one.
- **5:** The response conveys a vivid, coherent, persistent external place while
  remaining entirely grounded in supplied facts.

### 2. Imaginability

- **1:** The reader cannot form a useful picture or sketch from the response, or
  the stated layout is materially misleading.
- **3:** Main anchors can be pictured and roughly placed, but important
  relationships or orientations remain vague.
- **5:** The reader could sketch a clear, consistent scene from the narration;
  important anchors and relations are easy to imagine without coordinate
  recitation.

### 3. Natural use

- **1:** No useful environmental detail is reused, or landmarks are recited
  mechanically/inaccurately.
- **3:** At least one relevant anchor is reused naturally, but references are
  sparse, repetitive or partly map-like.
- **5:** Environmental details are integrated selectively and naturally, making
  narration vivid without reciting the packet or sketch.

### 4. Actionability

- **1:** The response obscures or misstates supported routes, reachability or
  available actions.
- **3:** The main supported option is understandable, though a material
  boundary (blocked/open, visible/reachable, known/unknown) is vague.
- **5:** Supported choices and material limits are clear and easy to act on;
  important unknowns remain explicitly unknown without overclaiming.

### 5. Continuity

- **1:** The response ignores the supplied snapshot/viewpoint, contradicts
  itself, or loses a committed feature change.
- **3:** It remains internally consistent for the main facts but weakly tracks
  viewpoint, route history or changed state.
- **5:** It attentively maintains stable anchors, viewpoint, return route and
  committed changes across the supplied transcript without inventing history.

### 6. Combat clarity and flow (combat rows only)

- **1:** Positions, engagement or movement are confusing or contradictory and
  make the encounter hard to follow.
- **3:** The main positions and action are understandable, but zone changes,
  cover or enemy locations need effort to reconstruct or slow the exchange.
- **5:** Positions, engagement, cover and enemy movement are immediately
  understandable and coherent without slowing the scene or reading like a
  tactical report.

Dimension 6 is not applicable to exploration rows. Dimensions 1-5 are used for
the S2 exploration-arm rubric means. On combat rows, score all applicable
dimensions including dimension 6, but do not use it in the B-versus-D packet
comparison because B has no combat rows.

## Row and arm scoring formula

For each valid row, average its five applicable dimension scores for
exploration, or its six dimension scores for combat. If multiple raters are
authorized, first average each dimension within the row across raters; the
owner's rating remains separately identified. Arm means are the unweighted
arithmetic mean of row means over completed matched rows. For B-vs-D and
candidate-vs-A, include only complete matched party/script/repeat groups; do
not impute missing ratings. The exact threshold computations and not-estimable
handling are in `README.md`.

## Sketch test

The owner completes at most six sketches from transcript alone, before seeing
the canonical fixture or answer key. Use exactly these matched rows:

- `E01`, `E02`, `E03`: P1 interior, repeat 1, arms A/B/D.
- `E13`, `E14`, `E15`: P4 landscape, repeat 1, arms D/A/B.

For each row, provide the transcript only; hide arm/order/model metadata and all
fixture files. Ask the owner to draw and label the scene, exits and visible
landmarks. Lock the sketch before comparing it with
`fixtures/interior_tavern.json` or `fixtures/landscape_village.json`. The scoring
key is the fixture's `expected_properties.sketch_anchor_ids` and
`sketch_relations`; schematic position labels are broad sectors, not metric
coordinates.

An expected anchor earns one correct placement only if it is represented (by
label or unambiguous symbol) and placed in the correct broad schematic sector
with required relation(s) intact. A missing or misplaced expected anchor earns
zero. Count each unsupported extra anchor/route assertion once as a false
positive. Across all selected rows calculate:

`Sketch placement score = 100 * correct expected anchor placements / (all expected anchor placements + unsupported extra anchors/routes)`

If there are no expected anchors (not expected for these fixtures), report not
estimable. Also report correct placements, expected placements, and false
positives as raw counts. Do not use the sketch score as a substitute for the
separate narration rubric or objective contradiction score.

No sketch, rating or score is filled by this preregistration.
