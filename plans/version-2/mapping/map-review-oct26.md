# Mapping review: spatial grounding, ASCII grids, and radar experiments

Status: Deliberation record and proposed research scope; not implementation approval
Recorded: 2026-10-27
Filename: Owner-requested `map-review-oct26.md`
Purpose: Preserve the mapping discussion and define the experiment that should inform the consolidated mapping implementation plan.

## 1. The problem to solve

The owner reports that NEQ's current spatial awareness is minimal and unsatisfying. It detracts from immersion: the imaginary game world does not consistently feel like an external place with stable geography, landmarks, routes, and positions.

The objective is not merely to prevent illegal moves or supply correct compass directions. It is to help the Narrator convey a coherent, persistent environment that players can inhabit, discuss, navigate, and change.

There is also a separate player-facing need. Internet-connected thin clients need a common map reference; a paper map held by one player is not automatically available to everyone else. A shared ASCII environment map is a plausible first solution, not merely a debugging aid.

## 2. Discussion outcome and decision status

- Retain ASCII grids and relative-threat radars as serious candidate designs. Do not discard them in favour of prose by architectural preference.
- Investigate whether they improve spatial reasoning, narrative continuity, and gameplay experience through controlled comparisons.
- Treat LLM input format and shared player-map usefulness as separate questions. A disappointing LLM result would not invalidate the player-facing map.
- Do not assume a coarse diagram is sufficient mechanical geometry. Python remains authoritative for committed state and action legality.
- The working hypothesis is that a hybrid of ASCII and concise explicit relationships may perform best. This is a hypothesis, not a decided requirement.
- Wait for the ongoing combat refactor and its required gameplay verification before consolidating combat mapping or integrating new combat spatial behaviour.
- This record does not create a goal, author an OpenSpec change, approve product implementation, or report any new experimental result.

The next step is a bounded mapping research goal, followed by a consolidated implementation plan informed by the evidence.

## 3. Material reviewed

Mapping drafts:

- [Mapping overview](mapping-overview.md)
- [World mapping](world-mapping.md)
- [Combat mapping](combat-mapping.md)
- [DM local grid](dm-local-grid.md)
- [DM regional grid](dm-regional-grid.md)
- [DM combat grid and engagement roster](dm-combat-grid.md)

Related repository contracts and implementation inspected during the review:

- `utils/location_path_finder.py`
- `utils/spatial_contract.py`
- `schemas/map_schema.json`
- `core/ai/atlas_builder.py`
- `core/ai/transition_atlas_builder.py`
- `core/ai/conversation_utils.py`
- `openspec/specs/tt-spatial-coordinate-resolution/spec.md`
- `openspec/specs/spatial-grid-embedding-solver/spec.md`
- `openspec/changes/combat-tactical-brain/specs/combat-tactical-brain/spec.md`
- `openspec/changes/combat-ally-controller/proposal.md`
- `openspec/changes/combat-turn-commit-and-receipts/proposal.md`
- `plans/v2-narrator.md`
- `plans/capture-arena.md`
- `.opencode/skills/neq-capture-arena/SKILL.md`

These are review-time references, not a frozen inventory of future integration points. Recheck active change status and current source before implementation.

## 4. Narrative and combat mapping: the useful distinction

Prefer different spatial resolutions and task-specific views of a coherent world over separate competing world models.

| Layer | Main questions | Suitable representation |
| --- | --- | --- |
| Regional | What lies beyond here? How do we get there? | Regions, routes, landmarks, travel costs |
| Exploration | Where are we? What connects? What can we perceive? | Location graph, exits, scene features, sensory relationships |
| Tactical | Can this actor reach, see, attack, or affect that target? | Encounter geometry and Python-computed action relationships |

Shared services should preserve stable location and feature identities and agreement about shared facts. This does not require identical storage or geometry at every scale.

```text
Authored topology + campaign changes + encounter state
                         |
               Python spatial queries
                         |
          +--------------+--------------+
          |              |              |
     Narrator view   Actor view      Player map
```

The Narrator, an enemy commander, and a player map have different knowledge permissions. They should receive consistent but appropriately scoped projections, not necessarily the same payload.

Reusing a map UI host and renderer interfaces is sensible. Treating tactical combat as only a visual profile of a room-connectivity graph would obscure different underlying requirements.

## 5. Why grids and radars deserve testing

A stable diagram may give the Narrator a stronger mental scaffold than a flat list of disconnected facts:

```text
[ Balcony ] [ North Door ] [ Stairs  ]
[ Windows ] [ Long Table ] [ Hearth  ]
[ Barrels ] [ Entrance   ] [ Kitchen ]
```

The desired outcome is not repeated map recitation. It is natural reuse of spatial anchors: entering beneath the balcony, crossing around the table, watching the stairs, returning to the same doorway, or seeing the consequences of a changed feature.

A relative radar may similarly improve communication about nearby threats and tactical options. It should be tested on viewpoint changes and crowded encounters rather than judged only on an attractive static example.

The complementary relationship is:

> The map helps the Narrator understand the scene; spatial rules constrain what can happen within it.

Python descriptions are not presumed superior. ASCII interpretation is not presumed reliable. Both propositions need evidence.

## 6. Architectural concerns to resolve, not reasons to reject maps

### 6.1 Schematic coordinates versus physical distance

The local-grid draft proposes Manhattan distance multiplied by area type to estimate travel time. Existing spatial contracts can instead place connected locations in neighbouring cardinal cells as a schematic embedding.

One layout step therefore does not inherently mean five feet, two minutes, or fifteen minutes. Prefer authored route length/time when available. Otherwise use an explicitly approximate policy or report distance as unknown.

Compressing a connection into a neighbouring display slot is acceptable presentation if labelled schematic. It must not invent physical adjacency, traversability, or a trustworthy compass bearing.

Coordinate frames and orientation need explicit conventions. The local and regional drafts currently use opposite Y-axis directions. Independently generated areas must not silently be treated as one metric coordinate system.

### 6.2 Connection, knowledge, perception, and traversal are different

Keep separate whether a connection exists, whether an exit is perceived, whether its destination is known, whether that destination is visible, and whether travel is currently permitted.

A concealed passage may exist without being known. A closed door may be known without revealing what is behind it. A distant tower may be visible without being directly reachable. Absence from a bounded prompt must not be interpreted as proof that something does not exist.

### 6.3 Bounded context without artificial amnesia

An adjacent-room view is useful but not enough for return journeys or questions about the wider world. A candidate context policy is:

- Always present: current location, relevant features, perceived exits, recent movement.
- Compact orientation: containing area/region and important known landmarks.
- On demand: broader routes, distant destinations, and detailed spatial queries.

Current `core/ai/conversation_utils.py` rebuilds and injects a complete module atlas. Adding a local grid alone will not establish the draft's promised token savings. The eventual implementation plan must reconcile existing atlas consumers and bounded projections without introducing contradictory map truths.

### 6.4 Stage and Actors

Separating environment features from occupants is a strong idea. A scene sector need not be a five-foot square, and ten occupants need not be forced into one cell merely because they share a descriptive anchor.

However, melee clusters and range bands are lossy summaries. If A can reach B and B can reach C, it does not follow that A can reach C. Distance to a cluster does not determine distance, cover, or visibility to every member.

Use summaries for orientation while retaining enough authoritative information to answer supported action questions. Do not infer precise legality from a coarse radar. Resolve the proposed radar's band gaps/overlaps and directional semantics before treating its shape as a contract.

The proposed attack-driven auto-snapping must not retroactively grant movement. Validate intent and movement, commit permitted effects, then narrate. An invalid proposed move has no mechanical effect; fail-open presentation is not permissive physics.

### 6.5 Environment changes and persistence

Stable feature IDs should distinguish scenery from movement obstruction, sight obstruction, cover, and active hazards/effects. A free-form phrase such as "North Door becomes Wall of Fire" is not sufficient to establish all of those mechanics.

Python validates proposed changes. Define which consequences persist after combat and how campaign-specific changes overlay reusable module assets. A destroyed door should not reappear merely because the encounter ended.

### 6.6 Regions are not necessarily modules

A module can contain one cellar, a city, a continent, or disconnected sites. Several modules may occupy the same geographical region. Separate geographical places and routes from adventure placements, even if a pegboard is a useful initial presentation.

Commit revealed geography before narrating it. A rumour about a northern forest must constrain later procedural placement rather than being contradicted when a module is selected.

Installed, placed, rumoured, discovered, and visited are different states. Module suitability includes geography and setting as well as level. Level suitability should not silently become a prohibition on player travel. Define the no-suitable-module outcome.

### 6.7 Existing foundations and unsafe assumptions

- Shared spatial contracts and helpers already exist; the plan should reuse them.
- `utils/spatial_contract.py:build_tactical_grid()` currently generates generic approach/cover labels. Field presence does not prove prose-grounded tactical quality or mechanical cover.
- `LocationGraph` currently keys nodes by bare location ID while loading multiple modules. Cross-module projections need collision-safe identities.
- The graph loader contains legacy load-time repair writes. A read-only map request must not accidentally become module remediation.
- Presentation fallback must not revive blocked routes using stale map artifacts.
- Persistence migration, generic worldview tables, and a new map ontology should not be adopted merely because an older draft proposed them.

## 7. Proposed controlled experiment

### 7.1 Questions

1. Does an ASCII scene grid improve the Narrator's spatial understanding and continuity?
2. Does a relative-threat radar improve tactical understanding and communication?
3. Does a hybrid outperform either format alone at an acceptable context cost?
4. Independently, does a shared player map improve orientation and collaboration?

### 7.2 Conditions

| Condition | Input |
| --- | --- |
| A: Current baseline | Current NEQ context, without the experimental map augmentation |
| B: Explicit relationships | Structured scene features, directions, exits, and supported spatial relationships |
| C: ASCII | Scene grid or relative radar plus the minimal legend needed to identify its contents |
| D: Hybrid | ASCII plus concise explicit relationships |

B, C, and D must be generated from the same fixture facts and contain semantically equivalent information. Shared background, task instructions, and information permissions remain identical. D may repeat relationships already encoded visually, but must not receive extra world facts or exclusive legal-action answers.

A measures improvement over the current experience; B/C/D isolate representation. Do not present an improvement over A alone as proof that ASCII itself caused it.

Keep model/provider/profile, question sequence, scene state, and supported mechanics fixed. Record actual resolved model/provider and any fallback. Randomise or counterbalance condition order; reset each independent trial so prior conditions cannot leak into later ones. Preserve full prompts and responses, fixture hashes, and the fact-equivalence audit. Use opaque condition labels for human review.

Measure token overhead rather than pretending all formats have equal length. An optional token-matched comparison is a separate analysis, not permission to remove essential facts from one arm.

### 7.3 Scene families

**Landscape/exploration**

- Village, bridge, woodland trail, visible distant tower, and an obstruction.
- Ask directions, plan a route around the obstruction, travel away, and return from another approach.
- Check geography, bearings, known versus unknown destinations, and visible versus reachable distinctions.

**Interior**

- Tavern with doors, furniture, stairs, balcony, and distinct NPC/feature anchors.
- Move between landmarks, speak across the room, ask what is visible/audible, change one supported feature, and revisit it.
- Check stable layout, viewpoint consistency, environmental use, and remembered consequences.

**Combat scene**

- Separate engagements, a ranged attacker, cover, and an elevated position.
- Ask for an assessment, change one actor's supplied position, switch viewpoints, and ask again.
- Check target/position consistency, radar comprehension, and no invented movement or knowledge.
- Initially test narration of supplied facts, not implementation of a new spatial engine. Any manually supplied distances/LOS are labelled fixture truth, not evidence that current NEQ computes them.

### 7.4 Staging and bounds

Stage 0: Inspect the existing rig and prerequisites; define fixtures, question scripts, expected properties, scoring rubric, and a fixed call/time budget before provider requests. Recheck the combat dependency and live-capture readiness. Tooling claims in older plans must be verified against current source.

Stage 1: Run paired scene-response trials to compare representations cheaply before live integration. A proposed initial ceiling is 36 single-response trials: four conditions, three scene families, three repetitions per condition. This is a starting research budget, not authorisation for unlimited retries, additional models, or a full factorial matrix. Each response may address a fixed set of scene questions. Do not call isolated prompt trials live gameplay captures.

Stage 2: Select the informative conditions from Stage 1, freeze a smaller multi-turn Arena matrix, and record its separate request/time budget before execution. Cover both 1-PC and 4-PC parties on relevant shared runtime paths. Include movement, return travel, viewpoint changes, and a supported state update. If the first stage is inconclusive, report that and justify any further trial rather than silently expanding the budget.

Landscape/interior research may proceed before combat consolidation. Combat prompt-only trials can use synthetic, clearly labelled scene facts; live combat integration and conclusions about gameplay legality wait for the refactor's required gameplay verification. Do not resume or modify another session's rollout goal to satisfy this dependency.

Stage 3: Provide blinded transcripts and representative shared-map renderings for owner/player review. Distinguish human orientation and collaboration from model reasoning. A socket transcript cannot establish browser readability or remote-client usability. Do not implement production thin-client map distribution merely to perform this research.

### 7.5 Evaluation

Objective properties:

- Correct exits, bearings, routes, and landmark relationships.
- Stable positions and features across turns and return journeys.
- No invented paths, unsupported movement, hidden-information leakage, or false precision.
- Agreement with the fixture's supported action facts and actual persisted runtime state where applicable.
- Correct handling of unknown/unresolved information and viewpoint changes.

Human rubric, proposed scale 1-5 with written anchors defined before review:

- Sense of place and external realism.
- Natural environmental use rather than map recitation.
- Clarity of available actions and routes.
- Continuity and attentive-DM quality.
- Shared-map legibility and usefulness for discussing plans.

Operational measurements:

- Input/output tokens, latency, logical requests, actual attempts, provider/fallback identity, and cost when observed.
- Unknown cost or absent telemetry remains unknown, never zero.
- Report per-scene results, sample sizes, variation, and counterexamples rather than only an aggregate winner.

Keep factual scoring separate from aesthetic preference. A beautiful but misleading map does not establish spatial reliability. Conversely, an LLM-format loss does not establish that player maps are unhelpful.

## 8. Capture ownership, safety, and evidence

Reuse the existing Capture Arena seeder, socket driver, and fixture/report helpers. Add only bounded experimental support; do not build a parallel gameplay runner or implement the broader unapproved rig tiers.

All live preparation, driving, evidence review, and verdicts are primary-orchestrator-owned. Use the repository venv, isolated `tmp/combat_capture/`, port 8360, and `NEQ_OPEN_BROWSER=0`. Never start, inspect, or stop port 8357 or modify the installed campaign.

Preserve uniquely named bundles under `tmp/router-rollout/mapping-research/<run-id>/` before teardown. Verify how the existing driver accepts and creates destinations before invoking it; these example research paths and condition names are not claims of existing CLI support. Never overwrite historical rollout evidence.

Record source HEAD/dirty-worktree identity, fixture/scenario versions, seed and party, requested/resolved model/provider, exact experimental prompts, transcripts, bounds and actual counts, applicable state snapshots, assertions, and server logs. Keep credentials and secret configuration values out of every artifact.

At review time, `openspec/changes/combat-turn-commit-and-receipts/reports/g7-verdict.md` records G7 as BLOCKED after provider-network failures. The capture skill also records an owner credential-rotation prerequisite. These are recorded prerequisites to recheck, not proof that a new session is still offline or that rotation has been completed. Never inspect credentials to establish readiness; obtain owner attestation where required.

Transport completion, provider-free tests, or driver exit zero are not live PASS. Missing evidence, timeouts, and unmet prerequisites remain explicit. Synthetic fixtures, prompt-only trials, and live-runtime evidence must remain distinguishable.

## 9. Deliverables and decision rule

The research should produce:

1. Reproducible fixtures, scripts/condition definitions, and provider-free tests for any tooling changes.
2. Preserved paired responses and, when prerequisites permit, live Arena evidence.
3. Objective scoring, operational measurements, and blinded human-review material.
4. A concise decision report separating local grids, regional views, tactical radars, hybrid context, and player-facing maps.
5. Recommended inputs and unresolved decisions for the consolidated mapping plan, without implementing that plan.

For each candidate, recommend retain, revise, reject, or inconclusive, citing observed strengths, failures, and limitations. The acceptable output is an evidence-backed recommendation, not a guaranteed grid victory. A small pilot cannot prove universal superiority or zero hallucinations.

If human review is pending, do not invent ratings or claim demonstrated immersion. If live work is blocked, preserve useful prompt-only findings but do not present the complete live objective as achieved. Report the missing evidence and next authorised step.

The eventual mapping plan should preserve the goal of an immersive, shared, spatially coherent world. The experiment decides which representations best support that goal; it does not replace it with mechanical correctness alone.
