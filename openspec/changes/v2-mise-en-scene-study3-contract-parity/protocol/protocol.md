# Study 3 Provider-Free Contract Protocol

## Scope and authority

This is the isolated provider-free protocol contract for identity
`mise-en-scene-study3-20261110`, protocol version
`neq.llm_staging_study3_delta.v1`. It defines the exact scene order, canonical
input references, system/task message templates, per-scene injected schema, and
generation-envelope record. It does not dispatch a request, create a real
ledger or allocation, or grant call authorization.

The approved cap is pinned to `neq-standing-authority-20261110` and
`neq-study3-pre-approved-20261110`. This is approval of the cap only;
software-preparation readiness remains PENDING and dispatch remains
unauthorized. Semantic review, owner ratings, and model-capability verdict
remain PENDING. Expected and conservative costs are ESTIMATES, not actual Study
3 costs.

Study 1 and Study 2 protocol artifacts, code, values, and evidence remain
immutable. Study 3 reads only the hash-bound canonical input bindings, source
packets, and expected bundles. It does not read generated responses, deltas, or
diagnostic copies. Its own manifest and paths are separate from both earlier
studies.

## Ordered scenes and canonical bindings

There are exactly three ordered scene bindings, one attempt per scene:

1. `into_the_deepvault:scene:ha003-i02`
2. `into_the_deepvault:scene:sd005-i03`
3. `xhalruuns_masquerade:scene:tsu001-ao02`

`input-bindings.json` carries the exact Study 1 source-packet and expected-bundle
paths and SHA-256 values, computed topology and gate-context references, module
IDs, topology node IDs, role-specific candidate IDs, and public base fact IDs.
Its Study 1 manifest and Study 2 manifest/input-binding hashes are pinned. The
three canonical expected bundles and source packets are read-only; the request
must copy their bound references exactly. Topology and gate-context hashes are
the canonical UTF-8 JSON SHA-256 of the exact approved topology object, using
`ensure_ascii=false`, `sort_keys=true`, and separators `(',', ':')`.

## Output contract

`model-contract.json` is the machine-readable normative contract. The system
message states the output rules in model-facing language, and
`output-contract.schema.json` is a template rendered by
`render_output_schema(scene_id)` into the exact injected JSON Schema for the
bound module and scene. Unknown keys are forbidden at the root and every nested
object.

The only root fields are `schema`, `input_refs`, `fixture_deltas`,
`stage_role_bindings`, `claims`, and `arrival_prose`. The payload limit is
65,536 UTF-8 bytes; duplicate object keys, non-finite values, numeric values,
unknown keys, arbitrary value objects/arrays, stale hashes, and unbound IDs are
invalid. Input references are exactly the bound scene, source packet, expected
bundle, topology, and gate canonical context. Reference IDs are 1-512
characters and SHA-256 values are lowercase 64-character hex.

Authored IDs use the exact module-qualified
`<module_id>:fact:study3-authored:<suffix>` namespace. The rendered schema uses
an escaped, anchored module-specific pattern and limits full fact IDs to 256
characters. Source/base fact IDs remain distinct. Each authored fact is closed
to `fact_id`, `subject_id`, `predicate`, `object_id`, and `value`. There are at
most 64 facts and at least the two required stage relations. The only
predicates are `approach_to_threshold`, `threshold_to_focal`, `usable_space`,
`light_gradient`, `sound_gradient`, `weather_gradient`, and
`visible_affordance`. Values are strings of at most 512 characters, booleans,
null, or closed `entity_ref`/`fact_ref` objects. Arbitrary objects and arrays
are forbidden.

Exactly one `approach_to_threshold` and one `threshold_to_focal` relation are
required. Their subject/object roles are respectively approach -> threshold
and threshold -> focal_anchor; both values are the literal JSON boolean
`true`, and each endpoint is selected in its corresponding role binding. A
`usable_space` fact subject is selected in the `usable_space` binding.
`stage_role_bindings` has exactly the ordered roles `approach`,
`threshold`, `focal_anchor`, and `usable_space`. Each role contains 1-16 unique
IDs chosen only from that scene's exact candidate list.

There are exactly three claims groups, ordered approach, threshold, focal, and
at most 32 claims in each. Claim IDs are unique, scene-qualified, and at most
512 characters. Claim references are limited to public base facts and this
delta's authored facts. Each span is 1-512 characters and an exact substring
of its linked segment. An invitation encodes `kind="invitation"`,
`choice="open"`, and `success="unspecified"`; factual claims encode null
choice and success. Prose does not assert a player choice or successful
outcome.

There are exactly three arrival segments, ordered approach, threshold, focal.
Each segment ID is the exact scene-qualified `<scene_id>:arrival:<role>` and
at most 512 characters; each text is 1-512 characters. Claims bind checkable
public spans to permitted fact IDs. Source/base facts, topology, provenance,
private or guarded facts, and protected unknowns cannot be overwritten or
promoted. Preserve all unprovided state as unknown and do not infer unsupported
direction, access, visibility, traversal, distance, scale, sensory metrics,
mechanics, cues, identities, or other facts.

## Provider-free generation envelope

`generation-config.json` records, but does not execute, the exact approved
envelope: OpenRouter `openai/gpt-6-luna`, `allow_fallbacks=false`, zero retries
and reruns, no tools, redirects, streaming, or continuation, `max_tokens=16384`,
and `timeout_seconds=720`. The cap is exactly three attempts total, one per
scene, bound to the fixed Study 3 identity and not a run ID or root.

Expected cost is approximately USD 0.01 and conservative cost approximately
USD 0.03. Both are labeled ESTIMATE. The independent hard ceiling is USD 0.05;
these figures do not state actual Study 3 spend or permit a dispatch. No live
client, transport, credential access, real ledger, allocation, or generation
call is part of this protocol task.
