# Spec Delta

## Purpose

Defines a prospective offline contract for scene-relationship authoring and projection prototypes, plus their provider-free checks and separately authorized evaluation. It does not define production runtime, persistence, schema, client, combat, or module-migration behavior.

## ADDED Requirements

### Requirement: Offline authoring SHALL preserve provenance and source unknowns (R1)

The offline prototype SHALL distinguish source-extracted facts, explicitly Builder-authored initial facts, and facts that remain unknown. It SHALL preserve source references only for material actually consulted, allow creative staging only within the supplied approved topology, and SHALL NOT write modules or runtime state.

#### Scenario: Extraction leaves unsupported relations unknown
- **GIVEN** source material establishes a landmark but not its route, compass bearing, distance, visibility, access, or sensory reach
- **WHEN** a source-faithful extraction emits the scene
- **THEN** it SHALL preserve the supported landmark and its source reference
- **AND** it SHALL mark each unsupported relation unknown rather than infer it from prose, adjacency, or a schematic cell

#### Scenario: Builder creativity remains distinguishable from extraction
- **GIVEN** a prototype Builder fixture uses supplied source material and an approved location topology
- **WHEN** it adds an initial approach, focal relationship, or terrain placement not stated by the source
- **THEN** that fact SHALL be marked Builder-authored, not source-extracted
- **AND** it SHALL remain within the supplied topology and cite only material actually consulted
- **AND** the prototype SHALL permit useful creative staging without requiring exhaustive atmospheric detail

#### Scenario: Prior runtime PCs are not copied into initial authorship
- **GIVEN** a fixture or source bundle contains PCs from prior play
- **WHEN** the offline prototype constructs an initial authored scene
- **THEN** it SHALL NOT copy those runtime PCs or their positions into the initial scene
- **AND** it SHALL distinguish any deliberately supplied synthetic evaluation party from authored scene inhabitants

### Requirement: Scene staging SHALL encode scope, orientation, and actionable relationships (R2)

Each fixture SHALL state its scene scope and whether compass orientation is known or unknown. It SHALL encode applicable approaches, thresholds, focal relations, multi-cell extents, and usable space as relationships, not just a feature inventory. Non-applicable elements SHALL be marked with a reason. Cells are schematic, not metric.

#### Scenario: Unknown world compass is not silently set to north
- **GIVEN** a scene establishes relative arrangement but gives no world-compass direction
- **WHEN** the scene is staged or projected
- **THEN** its compass direction SHALL remain explicitly unknown
- **AND** the prototype SHALL NOT default the diagram to north-up or invent a bearing

#### Scenario: Approaches, thresholds, and focal relationships are testable
- **GIVEN** a scene fixture has an approach, a threshold, and a focal anchor
- **WHEN** positional-coverage validation runs
- **THEN** it SHALL report the authored relationship from approach to threshold and from threshold to focal anchor
- **AND** it SHALL identify a missing required relationship even if the JSON/schema is otherwise valid

#### Scenario: Paths, terrain, boundaries, and usable space span their authored extent
- **GIVEN** a path, terrain feature, or boundary occupies multiple schematic cells and a separate space is usable for standing or interaction
- **WHEN** the scene is normalized and rendered
- **THEN** each feature's declared multi-cell extent SHALL be preserved
- **AND** the usable space SHALL remain identifiable as space, not be reduced to an isolated feature label
- **AND** the representation SHALL NOT imply metric width, distance, or movement cost

### Requirement: Scene identities SHALL preserve fixed anchors, mobile occupants, and separate frontages (R3)

The prototype SHALL preserve stable identities for fixed scene anchors and shared features while representing mobile occupants separately. Linked views of one place SHALL retain one place identity; separately authored frontages SHALL remain distinct relationships. The prototype SHALL NOT infer doors, exits, or access from frontage, adjacency, or visual proximity.

#### Scenario: One tavern has separate frontages and no inferred doors
- **GIVEN** two linked scene views show the same tavern from separate street frontages, and no source or Builder-authored fact declares a door
- **WHEN** the prototype validates their identities and renders their relations
- **THEN** both views SHALL reference the same tavern identity
- **AND** the two frontages SHALL remain separately represented
- **AND** no door, entrance, or traversable connection SHALL be inferred

#### Scenario: Mobile occupants do not redefine fixed anchors
- **GIVEN** a fixture includes fixed environmental anchors and initially placed mobile occupants
- **WHEN** a prototype movement example changes an occupant position
- **THEN** the occupant SHALL retain its identity and be represented separately from fixed anchors
- **AND** the example SHALL NOT relocate or mutate any fixed anchor

#### Scenario: Reciprocal scene bearings do not infer traversal or sensory facts
- **GIVEN** one linked scene view has a verified east relationship from place A to place B
- **WHEN** the prototype validates both views and their compass frames
- **THEN** the reciprocal view SHALL identify place A to the west of place B
- **AND** the validator SHALL NOT infer a door, traversal, access, visibility, audibility, or other sensory fact from that bearing
- **AND** the same place/anchor SHALL keep one identity across its views, while assigning one identity to distinct entities or using inconsistent cross-view compass relations SHALL fail with a stable diagnostic

### Requirement: Guarded camp trigger and unknown outcome SHALL remain separate from public scene knowledge (R4)

The offline knowledge fixture SHALL allow a GM-aware view to receive the guarded camp trigger while withholding it from public arrival and map projections. Arrival, looking at the camp, and investigating the tent SHALL neither reveal nor activate the surprise. Attempted fire-lighting SHALL be the only trigger condition represented. The trigger's effect SHALL remain unknown unless separately established; the prototype SHALL NOT invent an event, consequence, or mechanic.

#### Scenario: Arrival and investigation do not reveal or activate the surprise
- **GIVEN** the party arrives, looks over the campsite, or investigates the tent without attempting to light a fire
- **WHEN** public-arrival, public-map, and GM-aware fixture views are built
- **THEN** the public views SHALL NOT contain the guarded trigger or surprise
- **AND** none of those actions SHALL mark the trigger as met

#### Scenario: Attempted fire-lighting is the sole trigger condition and its effect stays unknown
- **GIVEN** a character attempts to light a fire at the camp
- **WHEN** the guarded-trigger fixture is evaluated
- **THEN** attempted fire-lighting SHALL be the only condition marked as satisfied
- **AND** the effect/result SHALL remain `unknown` and no narrative, damage, encounter, or rules outcome SHALL be fabricated
- **AND** the public projection SHALL still receive no guarded content unless a separate authorized resolution defines what may be disclosed

### Requirement: Unknown mechanics SHALL respect Firelight's migrated-family boundary (R5)

The prototype SHALL keep schematic placement distinct from distance, scale, access, line of sight, audibility, movement cost, and mechanical legality. It SHALL make no mechanical ruling. In any separately authorized runtime consumer, Firelight under the Python bridge may decide legality only for rule families migrated under accepted ADR-0033; unmigrated families retain their existing Python guards.

#### Scenario: Schematic cells do not create a metric or mechanical fact
- **GIVEN** a feature or route has only a schematic position and no separately established metric or action fact
- **WHEN** the prototype emits a relationship packet or schematic
- **THEN** distance, scale, travel time, access, line of sight, audibility, movement cost, and legality SHALL remain unknown
- **AND** cell co-location SHALL NOT establish any of those facts

#### Scenario: Only migrated rule families use Firelight authority
- **GIVEN** an example names a mechanical family as migrated or unmigrated
- **WHEN** the authority boundary is checked
- **THEN** a migrated family SHALL be marked as Firelight/Python-bridge-owned only in a separately approved runtime contract
- **AND** an unmigrated family SHALL remain Python-guard-owned
- **AND** this offline prototype SHALL call neither Firelight nor a provider

### Requirement: Projection conditions SHALL preserve matched facts without selecting a production format (R6)

The evaluation prototype SHALL be able to emit three matched conditions from the same semantic fact set: (A) structured relationships without a grid, (B) prose-only relationships conveying those same facts, and (C) the structured relationships plus a schematic grid. It SHALL bind each condition to the same scene/source identity and disclose no extra facts in one condition. These arms compare evidence; they do not select a production representation.

#### Scenario: Grid contribution is compared incrementally
- **GIVEN** the same scene facts are rendered in conditions A, B, and C
- **WHEN** positional assertions, owner ratings, and advisory-assessor ratings are reported
- **THEN** A versus C SHALL report the descriptive incremental difference associated with adding the schematic grid to the structured facts
- **AND** B SHALL remain a prose-only matched-facts comparison
- **AND** the report SHALL NOT claim a causal effect beyond this bounded comparison

#### Scenario: Narrator and cumulative public projections preserve scoped knowledge
- **GIVEN** a linked two-scene fixture has stable scene/feature identities, known visited and discovered facts, a rumoured fact, and GM-only route/trigger fields explicitly marked unknown to the public
- **WHEN** the offline prototype emits a Narrator-appropriate view and a cumulative public projection from the same authored facts and committed-discovery fixture
- **THEN** both projections SHALL preserve the same stable identities
- **AND** the Narrator-appropriate view SHALL keep GM-only route/trigger fields guarded and epistemically marked, while the public projection SHALL add only authorized discoveries
- **AND** the public projection SHALL preserve rumoured versus visited/discovered status, omit guarded unknowns without implying nonexistence, and SHALL NOT invent S5 regional geography

### Requirement: Provider-free checks SHALL test positional coverage and localize information loss (R7)

The offline suite SHALL validate provenance, topology compatibility, identity, declared scene-stage relationships and extents, protected unknowns, and public/GM knowledge boundaries. It SHALL measure positional coverage beyond schema validity and report whether a required fact was absent at source/extraction, absent from authoring, or lost during projection/rendering. It SHALL run without provider calls, a live server, or writes to modules or runtime state.

#### Scenario: Negative fixtures return specific deterministic diagnostics
- **GIVEN** provider-free fixtures for unsupported source relations, missing approach/threshold/focal coverage, truncated multi-cell extents, inferred tavern doors, moved fixed anchors, leaked camp triggers, or fabricated unknown mechanics
- **WHEN** validation runs repeatedly on the same inputs
- **THEN** each failure SHALL produce a stable diagnostic identifying the layer and relation at fault
- **AND** a companion fixture SHALL distinguish source absence from renderer loss of a fact present in the authored input
- **AND** validation SHALL NOT repair, rewrite, or persist any input

### Requirement: Held-out evaluation SHALL be version-bound, leakage-checked, and advisory-assessor-calibrated (R8)

The evaluation SHALL keep known examples development-only and use leakage-checked new holdouts. Freeze hashes for sources, facts, artifacts, rubric, and assessor configuration before scoring. Owner ratings bind to exact artifact versions. Freeze advisory output before the assessor sees owner scores; keep self-review, advisory output, and owner ratings separate. Proposed counts and thresholds are in `design.md` and require owner approval.

#### Scenario: Known examples calibrate but never enter the holdout
- **GIVEN** the original M1 artifacts or expanded owner examples are used for rubric/advisory-assessor development
- **WHEN** a held-out manifest is built
- **THEN** those examples and their derivatives SHALL be excluded from the holdout
- **AND** each holdout scene SHALL have a new source identity, a documented leakage check, and frozen hashes before scoring

#### Scenario: Assessor calibration and owner comparison expose denominators
- **GIVEN** an advisory assessor scores known examples with exact, pre-existing owner ratings and later scores held-out artifact versions before owner ratings are revealed
- **WHEN** the evaluation report is produced
- **THEN** it SHALL report exact agreement, within-one agreement, and mean absolute error by rating axis with paired-item denominators
- **AND** author self-review, independent advisory output, and owner ratings SHALL remain distinct
- **AND** insufficient exact owner-scored calibration pairs SHALL be reported as uncalibrated, not filled with fabricated labels

#### Scenario: Owner rates the exact held-out artifact version
- **GIVEN** an owner reviews a held-out artifact with its condition and content available as approved by the protocol
- **WHEN** legibility and usefulness ratings are recorded
- **THEN** each rating SHALL identify the artifact hash/version, scene, condition, axis, and rater
- **AND** no assistant score SHALL substitute for the owner rating

### Requirement: Prospective navigation evidence SHALL be bounded and independently adjudicated (R9)

If separately approved, live navigation SHALL cover each condition separately for P1 and P4 within the bounds in `design.md`. Critical failures have zero tolerance; non-critical outcomes use declared denominators and rates. Missing required evidence is BLOCKED. The primary orchestrator owns Capture_Arena execution and verdict after focused tests; a driver or advisory score alone cannot pass.

#### Scenario: Required route and return checks are judged per condition and party shape
- **GIVEN** an authorized episode includes approach, threshold, a scene transition, and return over multiple turns
- **WHEN** its narration and observations are checked against the frozen assertions
- **THEN** the report SHALL separately identify its condition and P1/P4 party shape
- **AND** it SHALL not pool results across conditions or party shapes

#### Scenario: Critical failure or missing evidence prevents a pass
- **GIVEN** a critical leak, false trigger, topology/route contradiction, moved fixed anchor, fabricated protected unknown, missing required episode, timeout, or absent required artifact occurs
- **WHEN** the primary orchestrator adjudicates the evidence
- **THEN** the affected cell SHALL be FAIL for a critical violation or BLOCKED for missing evidence
- **AND** neither SHALL be counted as a success or hidden by averaging
