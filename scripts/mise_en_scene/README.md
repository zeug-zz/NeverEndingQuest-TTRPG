# Proposed offline fixture contract (v1)

This package validates supplied fixtures only. It is standard-library-only and
does not author scenes with an LLM, read/write modules or runtime state, call
providers, or select a production representation.

## API

`ApprovedTopology` is a frozen dataclass passed separately from the fixture.
It contains `topology_id`, `module_id`, `scene_id`, `scope_id`, a tuple of
approved `compass_frames`, and a tuple of `fixed_anchor_ids`. Use
`validate_fixture(fixture, approved_topology, consulted_source_refs,
prior_pc_ids=())` to get a
`ValidationResult`; `is_valid` is true only when `diagnostics` is empty. Each
diagnostic has a stable `code` and JSON-style `path`.

IDs use `module:scene:local`, `module:scope:local`,
`module:entity:local`, `module:fact:local`, and `module:topology:local` forms.
The fixture's topology, scene, and scope IDs must match the separate topology
object. The object, not its ID string, supplies the frame and fixed-anchor
allowlists.

## Fixture shape

The JSON-shaped fixture has these required top-level fields:

- `schema_version: 1`, `module_id`, and `topology_id`.
- `scene: {id, scope: {id, kind}, orientation: {status, frame, provenance}}`.
  Orientation is either `{status: "unknown", frame: null, provenance: ...}`
  or known with a frame listed by `ApprovedTopology.compass_frames`. Known
  orientation provenance must be source-extracted or explicitly
  Builder-authored; extraction without compass evidence stays unknown.
- `fixed_anchors: [{id, kind}]` and
  `initial_mobile_occupants: [{id, kind}]` are separate identity lists. Fixed
  IDs must be in the approved topology, and no ID may occur in both lists.
- `facts: [{id, subject_id, predicate, object_id, status, value, provenance}]`
  hold relationship facts. References must resolve to this scene, scope, or
  listed entities. Unknown facts have `status: "unknown"` and `value: null`.
- `extension_seams` contains arrays named `multi_cell_extents`,
  `stage_relations`, `unknown_metrics`, `audience_knowledge`, and
  `arrival_claims`. The base `validate_fixture` checks their bounded JSON
  container/item shape only. The separate positional-coverage check formalizes
  `multi_cell_extents` as documented below; the other seams remain reserved.

Every `provenance` object is `{class, source_refs}`, where `class` is
`source_extracted`, `builder_authored`, or `unknown`. Source-extracted facts
require at least one source reference. All references must also occur in the
caller-supplied `consulted_source_refs` list/tuple. A reference string is not
evidence that a fact is true; Builder-authored facts remain distinguishable
from extracted facts.

The validator is read-only. It checks shape, stable module-qualified IDs,
references, duplicate identities, provenance/reference membership, and
orientation compatibility. Schematic cells and extents never establish
metrics, access, doors, visibility, or mechanics. Positional coverage is a
separate opt-in check described below; projection, audience-knowledge, and
arrival-prose checks remain out of scope.

`prior_pc_ids` is a separately supplied trusted list/tuple of qualified entity
IDs from runtime history. A matching initial mobile occupant is rejected, as
are occupants whose kind is `pc` or `player_character`; invalid input has stable
`PRIOR_PC_IDS_TYPE` / `PRIOR_PC_ID` diagnostics. Validation never removes,
converts, or otherwise repairs a PC record. A synthetic evaluation party, when
used, belongs in fixture-bundle metadata and is not an authored inhabitant.
The list is optional for backward compatibility. Without a caller-supplied
canonical prior-PC ID set, the validator cannot discover PC identity in
unknown external state: it rejects `kind: "pc"`, but cannot detect a known PC
disguised as an NPC. It does not infer identity. This is a limitation of the
supplied-input contract, not evidence that an unknown occupant is not a PC.

`mise_en_scene.fixtures.make_extraction_fixture()` and
`make_builder_fixture()` return fresh provider-free development bundles. The
extraction bundle keeps route, bearing, distance, visibility, access, sensory
reach, and compass orientation unknown. The Builder bundle adds topology-bound
approach/threshold/focal relationships marked `builder_authored`; these are
not source facts. Bundle provenance metadata names only the consulted fixture
material and labels it development-only, not held-out evidence or verified
legacy fact. These supplied fixtures do not test LLM authoring.

## Positional coverage subset

`validate_positional_coverage(fixture, reference_expected_coverage,
approved_topology, consulted_source_refs=())` in `coverage.py` returns a
`CoverageReport`. The reference expectations are a separate input, not embedded
in the candidate fixture: deleting a candidate fact or extent therefore does
not delete its obligation. `schema_valid` reports contract/coverage-data shape
validity; `coverage_valid` reports whether the reference's required
relationships and extents are present. An unevaluated or malformed input is
not a coverage pass. Diagnostics have stable `code`, `path`, and `layer` fields;
`schema` and `relationship_coverage` are separate layers, and coverage details
identify the candidate-authoring stage and resolved IDs.

The reference object has `schema_version: 1`, both fixed `stage_relations`
entries (`approach_to_threshold` and `threshold_to_focal`), an `extents` object
with `path`, `terrain`, and `boundary` arrays, and a `usable_spaces` array.
Each relation is either `status: "required"` with `from_id`/`to_id`, or
`status: "not_applicable"` with a non-empty `reason`. Required relationship
facts must occur in `fixture.facts` with the expected predicate and endpoint
IDs, resolve to listed fixed anchors whose `kind` matches the expected role,
and have `status: "known"`. Labels in `extension_seams.stage_relations` are not
evidence. An unknown fact is reported as unknown, not covered. A required
relationship cannot be waived by a candidate-side non-applicability claim.

Each required path, terrain, or boundary expectation names an entity ID and
at least two unique schematic cells. Its candidate record is an item in
`extension_seams.multi_cell_extents` with `{entity_id, status,
schematic_cells, reason}`. The expected and authored cell sets must match
exactly; missing and extra cells are reported separately. `status: "unknown"`
or `"not_applicable"` requires a non-empty reason, and neither can satisfy a
required extent. A usable-space expectation uses the same candidate extent
shape with the entity role `usable_space`; at least one usable space must be
required by the reference. Its cells may overlap path, terrain, or boundary
cells. That overlap is explicitly allowed and does not imply access, movement,
dimensions, or any other rule. Cell ordering is not semantic; duplicate cells
are invalid. Inputs are bounded to 256 items/cells per collection.

An explicitly non-applicable reference expectation appears separately in
`CoverageReport.not_applicable` with its reason. It is excluded rather than
counted as a covered relationship or extent. This task compares only the
separate reference expectation with the authored candidate; it does not infer
whether a fact disappeared at source, extraction, projection, or rendering.

## Linked-view identity and occupant movement examples

`mise_en_scene.identity.validate_linked_views(bundle)` returns the same
read-only `ValidationResult` shape as the base fixture contract. A bounded
`reference` object independently names canonical entities, their required
per-view occurrences, frontage relations, and bearing facts. Candidate
`identity_links`, `frontages`, and `bearings` are compared with that reference;
candidate names alone do not establish identity. Every fixed anchor in these
linked-view fixtures must have one reference-backed identity link. A `shared`
canonical entity must occur in at least two views, while each `view_local`
entity occurs in exactly one. The sample therefore binds two different local
tavern anchor IDs to one shared canonical tavern ID and gives each frontage a
distinct canonical identity and relation.

Frontage is only a frontage relationship. It does not establish a door,
entrance, exit, access, or traversal. Linked-view fixture facts using the
bounded prohibited predicate set for door/access/traversal/sensory claims are
rejected; this is structured-contract validation, not natural language
inference.

Each bearing must state a cardinal direction and compass frame explicitly.
The frame must be listed by both views' immutable `ApprovedTopology` values,
and both fixtures must explicitly use that known frame. Reciprocal view
bearings must use opposite directions. The sample uses east/west in a
synthetic approved compass frame solely to demonstrate reciprocal consistency;
`metadata.source_verified` is false, so this example does not claim that the
illustrative market/square geography or its bearings are source-verified.
Unknown or missing bearings are errors, never north/east defaults.

`mise_en_scene.identity.validate_occupant_movement(before, after)` accepts
separate `{fixed_anchors, mobile_occupants}` snapshots. It requires the fixed
anchor IDs, kinds, and schematic positions to remain identical, preserves
mobile occupant IDs and kinds, and requires at least one occupant position to
change. It is a pure fixture check and has no runtime movement or persistence
behavior.

`mise_en_scene.fixtures.make_linked_tavern_fixture("P1")` and the matching
`"P4"` call provide only synthetic party-shape/member-count metadata. Those
metadata do not contain PC positions and are not copied into authored scene
occupants; linked identity validation does not branch on party shape, and its
identity data is the same for both shapes. The companion
`make_fixed_anchor_mobile_occupant_fixture()` returns the before/after movement
example. Both constructors are development-only, not held-out evidence.

## Guarded camp knowledge and unknown mechanics (R4-R5)

`mise_en_scene.fixtures.make_guarded_camp_fixture()` returns separate
`candidate` and `guard_reference` dictionaries. The reference is not nested in
the candidate and independently fixes the public fact allowlist, guarded
visibility, trigger action, unknown effect, schematic positions, and protected
unknown-metric set. Candidate data cannot change the guard audience or trigger
to gain public access.

The source provenance is `plans/v2-mapping-pilot-owner-feedback.md`, Appendix H
(`Abandoned research camp: investigation mise-en-scene`), with the SHA-256 of
that section recorded in the fixture. Its arrangement and public descriptions
are marked `builder_authored_example` and `legacy_truth_verified: false`;
they are development examples, not extracted legacy module truth. The source
reference records consulted owner-feedback material only. No prior-play PCs
are initial occupants. Positions are north-up and schematic, with no measured
cell size.

`mise_en_scene.knowledge.build_knowledge_view(candidate, guard_reference,
audience=..., action=...)` accepts only the `public_arrival`, `public_map`, and
`gm` audiences and a finite action allowlist. Arrival, looking, and any of the
three tent-investigation actions do not meet the guarded condition. Only
`attempt_fire_lighting` marks that condition met in the GM view; this is a
condition check only, not trigger execution or effect resolution. The effect
remains unknown. Public arrival and map views omit the guarded fact, trigger,
payload, hidden ID, and source provenance for every accepted action. Unknown or
malformed audiences/actions fail closed.

Distance, scale, travel time, access, line of sight, audibility, movement cost,
and legality remain explicitly unknown; schematic positions establish none of
them. `classify_mechanics_authority(family_id, migrated_family_registry,
runtime_contract_approved=...)` returns only an authority label: Firelight/Python
bridge is named only for a family in the separately supplied migrated registry
when the separate runtime contract approval is true. Otherwise the label is
`python_guard`. It makes no mechanical ruling and calls no engine.

Focused command: `.venv/bin/python scripts/test_mise_en_scene_projection.py`.

## Matched projections and scoped linked scenes (R6)

`mise_en_scene.fixtures.make_linked_two_scene_knowledge_fixture()` returns a
fresh `{candidate, reference}` bundle. The candidate and its independent
reference are passed separately to
`mise_en_scene.projections.build_matched_projections(candidate, reference,
audience=...)`. The accepted audiences are `public` and `gm_narrator` only.
`knowledge.filter_scoped_fact_view()` uses reference allowlists for fact IDs
and topology record IDs; it returns only copied, authorized records. The
projection validates the complete candidate against its separate fact and
topology reference, then filters before rendering or hashing. Public filtering
and excludes the private camp scene ID, route/trigger fact IDs, and their source
references. The reference is an offline fixture contract, not an external
authorization service.

The four output arms are fixed: A is canonical structured relationships; B is
controlled prose without a structured fact payload; C appends only a sparse
ASCII schematic to A; D appends bounded Builder-authored arrival fragments to
C. B's prose spells out every fact field, including IDs, scene/subject/object,
status and knowledge status, audience, exact value text, and provenance class
and source references. It also spells out each scene node, topology link, and
schematic position, so the prose does not rely on companion binding metadata
to carry facts it omits. Rumoured known values are presented as recorded value
text with their epistemic status, not as unqualified assertions. B includes no
grid or staged-arrival fragment.

Each arm carries the same audience-filtered normalized facts, topology, IDs,
provenance, and hashes. C preserves the sparse address lines and appends one
bounded ASCII cell table per scene. Headers list only the actual sorted column
coordinates; rows retain signed coordinates; occupied cells show labels with
short per-scene markers mapped to stable anchor IDs in a legend. Co-located
anchors share a cell, while equal coordinates in different scenes remain
separate. A `.` means unspecified only, not blocked, and says nothing about
connection. Layout placement implies no adjacency or connection. The table is
limited to 64 layout records and never expands numeric coordinate gaps. The
grid re-renders layout already present in the structured layer and implies no
compass, metric, access, door, traversal, perception, or mechanical rule.
Output `content_sha256` is over the exact rendered UTF-8 text;
`artifact_sha256` binds that text to the shared fact-set, topology, and
provenance hashes.

The fixture preserves `known`, `discovered`, `visited`, and `rumoured` knowledge
statuses separately from `known`/`unknown` fact status. Public output keeps the
camp rumour and omits the GM-only route, trigger, and unknown effect. The GM
Narrator view receives those guarded facts with their IDs, provenance, and
epistemic statuses. No hidden source metadata is included in public outputs or
their hashes.

D uses exactly three supplied approach/threshold/focal prose fragments. Each
fragment is bound by a separately supplied approved text hash and exact known
fact IDs; its exported claim binding includes the corresponding fact
provenance. Editing prose while retaining its fact IDs fails closed. This base
projection protocol checks exact approved fragments only; it is not a general
natural-language or semantic validator. The R10 fixture protocol below adds
bounded typed-claim checks over those supplied fragments.

## Builder-authored staged arrivals (R10)

`mise_en_scene.arrival_fixtures.make_staged_arrival_fixtures()` returns fresh
`G`, `H`, and `I` development fixtures based on owner-feedback Appendices G,
H, and I. They are Builder-authored examples only: `held_out` and
`legacy_truth_verified` are false, and `llm_builder_tested` is false. The
source path, appendix heading, source-section SHA-256, and consulted source
reference are explicit. These fixtures are not evidence of legacy truth,
holdout quality, or LLM Builder capability.

`mise_en_scene.arrival.validate_staged_arrival(bundle, audience="public")`
checks a candidate against its separately supplied arrival reference. It
requires the approach, threshold, and focal stages in order; compares topology
and anchor placement; binds each typed claim and prose span to a fact ID, value,
and provenance; preserves known, unknown, and non-applicable light/sound/weather
cues; validates any next-section transition against topology and perception
facts; rejects guarded markers for public arrival; and requires invitations to
leave both choice and success unspecified. Builder-authored `north_up`
orientation is explicit and accepted only from the reference's approved frame
list; all coordinates remain schematic.

The typed claims form a bounded supplied-claim protocol, not NLP: exact text
hashes detect unapproved prose edits, while claim records independently bind
the supplied checkable spans to structured facts. Hashes alone do not establish
semantic equivalence, and the validator does not discover claims omitted from
the typed list. `build_staged_arrival_projections(bundle, audience=...)`
returns the existing matched A/B/C/D projections. All four preserve the same
fact/topology/provenance binding and arrival metadata; only D contains staged
prose and the exported typed-claim binding. Validation is read-only and
provider-free and does not write module or runtime state.

Focused commands: `.venv/bin/python scripts/test_mise_en_scene_authoring.py`
and `.venv/bin/python scripts/test_mise_en_scene_projection.py`.

## Stable negative diagnostics and fact lineage (R7)

`mise_en_scene.diagnostics.normalize_diagnostics(values,
default_layer=..., relation=...)` adapts the existing contract, coverage,
identity, knowledge, and projection diagnostics to immutable records with
`code`, `layer`, `relation`, `path`, and `severity`. Coverage retains its
separate `schema` versus `relationship_coverage` layers; its relationship
detail is normalized into `relation`.

`trace_fact_lineage(expectations, source_facts, extraction_facts,
authoring_facts, projection_outputs, approved_content_hashes)` checks facts by
qualified fact ID and predicate. Expectations independently state
`source_status: "supported"` or `"absent"` and `origin_class`:
`source_extracted`, `builder_authored`, or `unknown`. Supported facts must be
present with source provenance and unchanged semantic content at extraction
and authoring. The first missing stage is reported without cascading later
missing-stage errors. A source-absent Builder fact may begin at authoring but
must have `builder_authored` provenance; any cited source references are carried
as supplied and must be checked against the consulted-reference contract. A
source-absent unknown produces an informational `SOURCE_ABSENCE_UNKNOWN`; the
source may omit that unsupported relation, but extraction, authoring, and each
projection must retain an explicit unknown record. Missing downstream records
produce `EXTRACTION_UNKNOWN_MISSING`, `AUTHORING_UNKNOWN_MISSING`, or
`PROJECTION_UNKNOWN_MISSING` at the relevant layer/condition path, and any
downstream promotion to known is an error.

Projection checks inspect each actual A/B/C/D `binding.facts` record, not its
`fact_ids` list, and compare semantic fields to authored records. The actual
rendered `content` is hashed and compared with an independently supplied
approved hash for each condition; self-reported output hashes alone do not
prove fact presence or render integrity. `diagnose_guarded_content()` provides
a bounded exact-marker camp-leak check against protected values supplied from
the independent reference. These are provider-free checks over supplied
records and outputs; none writes or repairs inputs.

R10 prose tamper checks currently bind supplied fragments to separately
approved hashes and fact IDs, and the lineage utility compares the full actual
render against approved per-condition content hashes. They flag changed text
at the projection content path but do not classify its meaning or locate a
specific claim span. This is intentionally not general natural-language
validation; Task 1.10 owns the focused staged-arrival semantic diagnostics.

## Proposed R8 holdout manifest (offline tooling only)

`mise_en_scene.evaluation.load_known_examples()` returns the detached,
development-only catalog pinned to the 16 original M1 artifact IDs/hashes and
nine expanded owner-example sections. Owner section hashes are retained as
provenance, while exact example-artifact hashes and fingerprints cover only the
selected schematic/arrival artifact text; rating and review commentary is
excluded from those fingerprints. The catalog contains no ratings. It is
validated against its pinned source-provenance envelope and canonical content
hash before use; each proposal records 150 source/derivative pairs (6 scenes x
25 known examples).

Call `fingerprint_source_text(source_text)` to derive the stable bounded text,
layout, and feature token fingerprints expected by the proposal API. It uses the
`mise-en-scene-lexical-fingerprint-v1` tokenizer and is a lexical screen, not a
semantic comparison. For each proposed scene, supply exactly:

- `scene_id`, `source_identity`, `source_ref`, and `source_text`;
- `lineage_status` (`independent` or `derived`) and `adaptation_lineage`;
- the fingerprint helper's `layout_tokens` and `feature_tokens`; and
- `projection_candidate` plus its independent `projection_reference` for the
  existing A/B/C/D projection builder.

`build_proposed_holdout_manifest(scenes, assignment_seed, test_sha256=...,
rubric_sha256=..., assessor_sha256=...)` requires exactly six distinct scenes,
emits 24 matched artifacts and 48 P1/P4 episode assignments, and uses
SHA-256-ranked ordering (`sha256-rank-v1`) rather than a language PRNG. Exact
identity/reference/text-or-section-hash matches and declared known ancestry are rejected;
bounded text, layout, and feature overlaps are marked `REVIEW_REQUIRED` rather
than treated as semantic leak detection. Text and projected-artifact text use
at least 3 shared tokens and 200,000/1,000,000 Jaccard ppm; layout uses at least
2 shared tokens and 250,000 ppm; features use at least 3 shared tokens and
250,000 ppm. Exact non-empty token-set overlap also requires review. Unresolved
declared derivatives are rejected. The policy and thresholds are included in
the leakage summary and hash envelope. `verify_proposed_manifest()` re-derives
projections, leakage records, assignment, and the complete
source/fact/artifact/fixture/test/rubric/assessor/seed/order hash envelope.

This API creates only an in-memory `PROPOSED`, `NOT_AUTHORIZED` record. It does
not select real holdout sources, persist or publish a manifest, score artifacts,
call a provider, or authorize evaluation. `freeze_manifest_binding()` requires
an external reference bound to the exact candidate, seed, and order hashes; it
only verifies those bindings and never authenticates a human or authorizes
scoring. Synthetic approvals must set `test_only: true` and use a
`synthetic-test-only:` reference. A changed candidate, seed, or order requires
fresh approval binding. This task does not mark the protocol or any owner
approval as frozen.

### Supplied-score calibration arithmetic

`mise_en_scene.calibration.summarize_supplied_scores(records)` accepts at most
4096 exact-version score records with artifact SHA-256, qualified scene ID,
condition, axis, role, rater, integer score (1-5), and phase. It joins owner and
independent-advisory scores only on the exact phase/artifact/scene/condition/axis
key, preserves author self-reviews separately, and reports paired counts,
agreement, within-one agreement, absolute error, and MAE independently by phase,
condition, and axis. Rates and MAE remain null until an axis has six exact
owner/advisory pairs. `calibration_by_axis` combines exact pairs across the
known calibration examples to meet that six-pair floor; `paired_metrics` keeps
all phase/condition/axis strata visible. Holdout conditions are never pooled.
Unpaired counts exclude matched owner/advisory records while retaining
self-reviews separately. These are supplied records only: rater roles are not
authenticated and the function grants no scoring authorization. No provider is
invoked.
