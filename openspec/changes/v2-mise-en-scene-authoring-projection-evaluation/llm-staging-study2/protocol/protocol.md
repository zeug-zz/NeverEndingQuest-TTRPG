# Study 2 Delta-Only Output Protocol

## Scope and authority

This is the separate, provider-free Study 2 contract envelope. It applies only
to `ha003-i02`, `sd005-i03`, and `tsu001-ao02`. It does not amend or replace the
Study 1 protocol, inputs, runtime evidence, or output records. The contract,
in-memory hydrator, and deterministic evaluation entrypoint do not dispatch a
model or define execution parameters.

## Canonical input references

`input-bindings.json` binds each scene to the Study 1 staging manifest's exact
source-packet path/hash and expected-input path/hash. The expected-input path is
the expected-bundle ID. The topology ID is read from that expected bundle's
`approved_topology.topology_id`. The topology SHA-256 is computed by the gate
from that raw topology object's canonical UTF-8 JSON serialization, using
`ensure_ascii=false`, `sort_keys=true`, and separators `(',', ':')`.

The gate-canonical-context ID is
`<scene_id>#gate-canonical-context:<topology_id>` and its hash is that computed
topology SHA-256. Neither value is accepted from a response as authority: each
response reference is compared with the binding recomputed from the frozen
Study 1 files. The source packet and expected bundle are read-only references;
their content is not included in a Study 2 response or returned as mutable
objects by the contract API.

## Response envelope

The only root properties are `schema`, `input_refs`, `fixture_deltas`,
`stage_role_bindings`, `claims`, and `arrival_prose`.

- `input_refs` contains the exact scene, source-packet, expected-bundle,
  topology, and gate-canonical-context IDs/hashes for the requested scene.
- `fixture_deltas.facts` contains only new Builder-authored fact records.
  Their provenance is derived by the deterministic gate; source facts, base
  facts, entities, topology nodes/edges, and canonical extension data are not
  response fields. Authored fact values are a bounded scalar or a closed
  `entity_ref`/`fact_ref` object; arbitrary JSON objects and arrays are not
  values. Fact and entity references are checked against the selected scene.
- `stage_role_bindings` selects only existing topology IDs from that scene's
  approved role-specific candidates. It cannot add or move a node.
- `claims` refers to public base or newly authored fact IDs and binds a short
  exact span to one arrival segment. Claim payloads do not repeat fact values,
  predicates, provenance, or topology.
- `arrival_prose` has exactly three segments in approach, threshold, focal
  order. It contains prose only, not a copy of topology, source facts,
  expected-bundle content, or model-trusted metadata.

Every nested object is closed. Unknown properties, wrong scenes, unknown IDs,
stale hashes, base-fact IDs used as authored IDs, unsupported fact-value
shapes, duplicate JSON keys, non-finite numbers, and topology/base-fact
overwrite attempts are rejected. Failures expose stable metadata-only codes;
they do not include source text or generated prose.

## Deterministic hydration and Study 1 gates (S2.2)

`validate_delta_output` first runs the strict delta validator above. Only after
it accepts the scene binding and exact hashes does the gate retain fresh
immutable byte snapshots of the bound source packet and expected bundle, check
their hashes and cross-references, and construct a full output in memory. Each
Study 1 gate call receives freshly parsed copies; neither canonical bytes nor
the files are mutated or written.

The hydrator follows the existing hand-assembled Study 1 fixture pattern:
canonical scalar source facts, anchors, protected unknowns, source provenance,
and topology come from the frozen expected bundle; only authored delta facts,
role-bound staging relations, claims, and the three prose segments come from
the validated delta. Composite source values are retained verbatim in the
bounded `audience_knowledge` seam because the legacy fixture fact validator
accepts only scalar fact values.
Study 2 authored fact IDs use their separate `study2-authored` namespace in
the delta. The hydrator maps them deterministically to bounded legacy fact IDs
and rewrites every corresponding claim/relation reference; collisions with
canonical or other projected facts fail closed. The submitted delta and its
hash retain the original Study 2 IDs.

The resulting full envelope is passed to the unchanged
`mise_en_scene.llm_staging.output_gates.validate_model_output`, which continues
to run schema, fixture/provenance, topology/identity, positional-coverage,
protected-unknown, source/knowledge-boundary, agency, and guarded-marker checks.
The report returns `delta_artifact_sha256`, `hydrated_output_sha256`,
`deterministic_status`, `scene_status`, and bounded diagnostics. A deterministic
PASS is not a study or scene PASS: semantic review and owner rating remain
`PENDING`, and the Study 1 gate's scene status remains `BLOCKED` pending that
review.

Focused negative coverage distinguishes the full-gate cases from attacks that
the closed delta cannot represent. Removing either authored stage-relation fact
and its claim remains a valid delta and reaches the unchanged gate, which
reports `MISSING_RELATION`. A known `light_gradient` or `sound_gradient` fact
also reaches that gate and is rejected as `PROTECTED_UNKNOWN_PROMOTED` because
those cues remain protected unknowns for these references. The delta schema
rejects `distance` and `mechanic` predicates before hydration. It likewise
rejects prescribed invitation choices/outcomes, source/base-fact or provenance
payloads, and attempted topology replacement; those are contract rejections,
not claimed full-gate coverage.

Missing usable-space coverage is not expressible in an accepted delta: all three
frozen scenes have exactly one approved usable-space candidate, the closed
contract requires a nonempty binding to it, and hydration deterministically
constructs its required singleton schematic extent. Tests therefore assert
pre-hydration rejection of a missing/empty usable-space binding or an attempted
extent override; they do not claim that the old gate observed missing coverage.
The same boundary applies to source values/provenance and fixed/mobile identity:
they are gate-owned canonical data, and attempted response fields are rejected
as unknown keys. Hydration parity checks explicitly compare all scalar source
facts that the frozen legacy fixture represents (with exact values and
source-reference provenance), all source values and source pointers/refs in the
audience-knowledge seam, protected unknowns, topology, fixed anchors, and mobile
occupant IDs. Composite source values stay outside the legacy fixture's scalar
fact records but are retained in that seam; the delta cannot replace or mutate
them.

The three hand-assembled (not model-generated) delta references are under
`protocol/references/`. They use only each scene's frozen inputs, topology
anchors, source description, and the two explicitly authorized stage
relations. Claims bind both authored stage relations and a short public source
type fact; the references avoid echoing long source fact values into the
guarded-marker scan. Study 1's required legacy metadata value
`llm_builder_tested=true` is retained only to satisfy its frozen envelope and
does not state that these references were model-tested. These references and
their machine-gate results carry no semantic or owner approval.

## Study 1 preservation

The contract reads Study 1 manifest, expected inputs, and source packets only to
verify hashes and derive immutable IDs/allowlists. It performs no writes. The
Study 1 protocol remains at
`openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/llm-staging-protocol/`;
runtime evidence remains at
`tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging/`. Both
byte sets are frozen and are not altered by this protocol.

## S2.4 offline preparation status

The separate prompt, generation configuration, staging manifest, and sizing
reports are materialized for owner/Overseer review. The three hand-assembled
reference counts use `APPROXIMATE` UTF-8 bytes divided by three, rounded up; this
is a documented heuristic, not a model tokenizer. The request-input estimate
counts the exact system and substituted user message contents constructed by
the Study 2 client, with JSON/message framing overhead explicitly not counted.
The report uses only the historical, hash-verified availability listing and
labels its three-scene dollar amount `ESTIMATE`. No provider or HTTP call was
made. Materialization is not owner cap approval, Overseer step-(a) approval, or
generation authorization.

## Owner-approved envelope amendment (2026-11-10)

Ruling `neq-study2-owner-cap-20261110` approves the active generation envelope
of `max_tokens=16384` and `timeout_seconds=720`, overriding the earlier
formula-derived proposal of 6144/360. The formula remains recorded as a sizing
proposal only. The cap remains exactly three attempts, one each for
`ha003-i02`, `sd005-i03`, and `tsu001-ao02`, using `openai/gpt-6-luna` via
OpenRouter, with no fallback, retries, reruns, or tools. Overseer step-(a)
approval is recorded separately as `neq-study2-step-a-approved-20261110`.

The existing conservative STOP behavior remains for identity failures,
transport errors, and non-200 responses; remaining attempts are unspent. A 200
response with invalid, truncated, or gate-failing content consumes that scene's
attempt and the study continues with the next scene, as clarified by
`neq-study2-gh-restored-20261110`. These recorded rulings do not themselves
create or record approval-fence files or executed calls.
