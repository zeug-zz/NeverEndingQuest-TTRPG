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

Each fixture SHALL state its scene scope and distinguish extraction-unknown compass orientation from explicitly Builder-authored orientation. Authored orientation SHALL be checked against approved topology/compass frames. Fixtures SHALL encode applicable approaches, thresholds, focal relations, multi-cell extents, and usable space as relationships; non-applicable elements SHALL have a reason. Cells are schematic, not metric or mechanical.

#### Scenario: Extraction leaves unsupported compass orientation unknown
- **GIVEN** source material establishes relative arrangement but gives no world-compass direction and no Builder orientation is supplied
- **WHEN** the scene is extracted or projected
- **THEN** compass direction SHALL remain explicitly unknown
- **AND** the prototype SHALL NOT default the diagram to north-up or invent a bearing

#### Scenario: Builder-authored north-up orientation is explicit and consistent
- **GIVEN** approved topology and a compatible compass frame, and a Builder explicitly authors north-up
- **WHEN** the scene is staged and orientation is validated
- **THEN** north-up SHALL be marked Builder-authored and accepted only if consistent with the approved frame
- **AND** the orientation SHALL NOT establish metric distance, access, or legality

#### Scenario: Conflicting Builder orientation is rejected
- **GIVEN** an explicitly Builder-authored orientation conflicts with approved topology or compass frames
- **WHEN** orientation validation runs
- **THEN** the fixture SHALL fail with a stable orientation-conflict diagnostic
- **AND** the prototype SHALL NOT silently rotate, default, or rewrite the approved topology

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
- **AND** the representation SHALL NOT imply metric width, distance, movement cost, or legality

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

The evaluation prototype SHALL emit four conditions from the same normalized semantic fact set: (A) structured relationships, (B) prose-only matched-facts control, (C) A plus schematic grid, and (D) C plus Builder-authored staged arrival prose. Each condition SHALL bind the same scene/source identity, fact IDs, provenance, topology, and any sensory-gradient or affordance facts used. D adds presentation/staging, not facts; the comparison SHALL NOT select a production representation.

#### Scenario: Four conditions preserve identical facts and provenance
- **GIVEN** a scene fixture has normalized facts, topology, provenance, and any authored sensory-gradient or affordance facts used
- **WHEN** the prototype emits conditions A, B, C, and D
- **THEN** all four SHALL preserve the same fact IDs, provenance, topology, and semantic facts
- **AND** B SHALL remain prose-only, C SHALL add only the schematic grid, and D SHALL add only staged arrival presentation to C
- **AND** D SHALL disclose no extra factual information or convert unknown/non-applicable cues into known facts

#### Scenario: Representation increments remain descriptive
- **GIVEN** matched A/B/C/D artifact versions and their ratings/assertions
- **WHEN** evaluation results are reported
- **THEN** A-versus-C SHALL describe the grid increment and C-versus-D SHALL describe the staging increment
- **AND** D-versus-B SHALL describe the combined-shape comparison
- **AND** no comparison SHALL claim an automatic winner, general causal effect, or production-format choice

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

The evaluation SHALL exclude known examples from leakage-checked holdouts and freeze source, fact, artifact, rubric, and assessor hashes before scoring. Owner ratings SHALL bind to exact artifact versions; self-review, advisory output, and owner ratings SHALL remain separate. Proposed counts and thresholds in `design.md` require owner approval.

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

#### Scenario: Supplied-fixture projection does not establish LLM Builder staging
- **GIVEN** the offline prototype validates or projects supplied fixtures
- **WHEN** the prototype's evidence and any future LLM-authored staging evaluation are described
- **THEN** the fixture results SHALL NOT be represented as evidence that an LLM Builder can stage scenes
- **AND** any LLM-authored staging evaluation SHALL require separate authorization, budget, protocol, and source provenance
- **AND** it SHALL NOT be treated as a current task or provider call

### Requirement: Prospective navigation evidence SHALL be bounded and independently adjudicated (R9)

If separately approved, live navigation SHALL cover all four conditions separately for P1 and P4 within the proposed bounds in `design.md`. Critical failures have zero tolerance; non-critical outcomes use declared denominators and rates. Missing required evidence is BLOCKED. The primary orchestrator owns Capture_Arena execution and verdict after focused tests; a driver or advisory score alone cannot pass. Results SHALL NOT be partially pooled across conditions or party shapes.

#### Scenario: Required route and return checks are judged per condition and party shape
- **GIVEN** an authorized episode includes approach, threshold, a scene transition, and return over multiple turns
- **WHEN** its narration and observations are checked against the frozen assertions
- **THEN** the report SHALL separately identify its condition and P1/P4 party shape
- **AND** the proposed 6-scene, 4-condition protocol SHALL schedule 48 episodes total, 24 for each party shape
- **AND** it SHALL not pool results across conditions or party shapes

#### Scenario: Critical failure or missing evidence prevents a pass
- **GIVEN** a critical leak, false trigger, topology/route contradiction, moved fixed anchor, fabricated protected unknown, missing required episode, timeout, or absent required artifact occurs
- **WHEN** the primary orchestrator adjudicates the evidence
- **THEN** the affected cell SHALL be FAIL for a critical violation or BLOCKED for missing evidence
- **AND** neither SHALL be counted as a success or hidden by averaging

### Requirement: Builder-authored staged arrival prose SHALL remain bound to the structured scene (R10)

Builder-authored arrival prose SHALL present an actionable approach-to-threshold-to-focal hierarchy using the same structured fact IDs and provenance. It SHALL add no topology, metrics, mechanics, access, or guarded content. Checkable prose-only facts SHALL produce localized diagnostics; unknown and non-applicable cues SHALL remain so.

#### Scenario: Arrival hierarchy and sensory transition match authored facts
- **GIVEN** a fixture has an authored approach, threshold, focal anchor, known light/sound/weather cues, and a topology/perception-valid next-section relation
- **WHEN** the D Builder-authored arrival presentation is projected
- **THEN** prose SHALL stage approach, threshold, then focal point and bind each checkable statement to the same structured fact IDs and provenance
- **AND** authored cue gradients and transition SHALL respect known facts and topology/perception
- **AND** visible affordances MAY invite action but SHALL NOT prescribe a choice or successful outcome

#### Scenario: Prose-only actionable facts are localized while atmosphere remains flexible
- **GIVEN** arrival prose contains non-actionable atmospheric framing and a checkable actionable claim absent from structured facts
- **WHEN** provider-free diagnostics compare prose with the structured layer
- **THEN** non-actionable framing MAY remain
- **AND** the unsupported actionable claim SHALL be flagged with its missing fact and prose location

#### Scenario: Topology or fixed-anchor relocation in prose is rejected
- **GIVEN** paired arrival fixtures where one prose version invents a connection and another relocates a fixed anchor from the structured scene
- **WHEN** D is validated
- **THEN** both invalid versions SHALL fail with localized topology/anchor diagnostics
- **AND** prose SHALL NOT alter the approved topology or fixed-anchor position

#### Scenario: Fabricated sensory gradient is rejected
- **GIVEN** paired fixtures where one arrival description invents a light, sound, or weather gradient and another preserves an unknown or non-applicable cue as such
- **WHEN** prose is checked against structured sensory facts
- **THEN** the fabricated gradient SHALL fail with a localized diagnostic
- **AND** the unknown/non-applicable cue SHALL remain unknown/non-applicable

#### Scenario: Guarded content cannot leak into arrival prose
- **GIVEN** a staged scene contains a guarded fact unavailable to the public arrival view
- **WHEN** the D prose is projected for that public view
- **THEN** any prose revealing or activating the guarded fact SHALL fail with a localized knowledge-boundary diagnostic

#### Scenario: Arrival invitation does not prescribe player choice or success
- **GIVEN** a valid scene with visible affordances and a prose variant that dictates a player choice or successful outcome
- **WHEN** D is validated
- **THEN** the invitation grounded in visible affordances MAY pass
- **AND** the prescriptive choice or success claim SHALL fail with a localized agency diagnostic

### Requirement: Study 2 preparation SHALL bind deltas to immutable canonical inputs (R11)

Study 2 SHALL bind each delta to the frozen scene, topology, and expected-bundle IDs/SHA-256. It SHALL accept only those references, authored fixture deltas, stage-role bindings, claims, and arrival prose; reject unknown keys, stale/unknown hashes, and topology/base-fact overwrites; then hydrate the full fixture in memory and run all existing safety gates without mutating or persisting canonical inputs. See [`llm-staging-study2/design.md`](../../llm-staging-study2/design.md).

#### Scenario: Delta output is checked against the gate-held canonical fixture
- **GIVEN** a frozen scene bundle and approved topology have known IDs and SHA-256 values
- **WHEN** a study 2 delta is validated
- **THEN** only exact input references and the allowed authored delta fields SHALL be accepted
- **AND** unknown keys, stale or unknown hashes, and attempted topology/base-fact overwrites SHALL be rejected
- **AND** the gate SHALL hydrate a full fixture in memory and run all existing safety gates without changing or persisting the canonical inputs

### Requirement: Study 2 preparation SHALL remain isolated and execution-disabled (R12)

Study 2 SHALL use a separate run root and fixed ledger, distinct from study 1. Its three-attempt cap SHALL NOT vary by run ID/root. Preparation SHALL make zero network/provider calls. Dispatch SHALL require owner cap approval and Overseer step-(a) review, reserve before HTTP, and fail closed on unsafe ledger or identity state.

#### Scenario: Unapproved or unsafe state cannot dispatch or reset the study cap
- **GIVEN** either required approval is absent, the studywide ledger is missing/corrupt/pending, or a run ID/root is repeated
- **WHEN** preparation or an execution preflight is attempted
- **THEN** preparation SHALL make no network/provider call and the execution preflight SHALL fail closed
- **AND** a run ID/root change SHALL NOT reset the fixed three-attempt cap
- **AND** no study 1 ledger or artifact SHALL be reused or modified
