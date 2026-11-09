# LLM Builder Mise-en-Scene Staging Study Protocol

**Status: protocol package frozen for Overseer review; no generation call is
made or permitted by this implementation step.** The required handoff status is
recorded in [`protocol.draft.md`](protocol.draft.md). The owner ruling is S,
2026-11-08T20:41:09Z, item 2; sequence step (a) ends at planner/Overseer
verification before any call. The companion draft file is the required handoff
status record; this document is the detailed protocol.

## 1. Scope and decision boundary

This is a three-attempt, source-bound LLM Builder staging study. It is separate
from the offline fixture study, the Section 2 holdout evaluation, production
acceptance, and gameplay. Results apply only to the frozen inputs, prompt,
output contract, route, parameters, and reviewed outputs. They do not select a
production representation, authorize module writes/backfill, establish runtime
behavior, or replace M1/D1, SP3/SP3b, owner, or live-capture evidence.

This document and the adjacent prompt/config/artifact hashes are implementation
artifacts for Overseer review. The current work does not dispatch a provider
request, access a credential, run gameplay, start a server, use a port, or
modify production routing. Step (b) requires a separate explicit transition
after this package is reviewed.

## 2. Approved scenes and source bindings

The owner approved exactly these three scenes, in this order. Duskmire Hollow
was dropped. Two scenes from Into the Deepvault are acceptable. Manual lineage
review remains a pre-call gate even though no semantic-derivative concern was
raised.

| Order | Scene ID | Source reference | Source SHA-256 | Canonical packet SHA-256 |
| --- | --- | --- | --- | --- |
| 1 | `into_the_deepvault:scene:ha003-i02` | `modules/Into_the_Deepvault/areas/HA003_BU.json#locations[locationId=I02]+map.rooms[id=I02]` | `b90e6348d361d2978103af88a2b9b6b064f0a7d759b001585b7227e7c327a159` | `165d983bc572ba2f900a69bbb893e4f76222b2ca5e1923f0b4bea4693fd26f3e` |
| 2 | `into_the_deepvault:scene:sd005-i03` | `modules/Into_the_Deepvault/areas/SD005_BU.json#locations[locationId=I03]+map.rooms[id=I03]` | `d625edb639b9ee935709afdc39a31f5929db52699b3ee14d819202da80adbb9a` | `628b1d68a7d2dd5ab441e20cc031b58c7ee6fedb7ad466a6eaad175214a4a6ee` |
| 3 | `xhalruuns_masquerade:scene:tsu001-ao02` | `modules/Xhalruuns_Masquerade/areas/TSU001_BU.json#locations[locationId=AO02]+map.rooms[id=AO02]` | `1f77e3c4598efddf0db3f9a6f52015b98e00f03f4a37fe2e91882813e4a97b2d` | `2a44cebcc17617e5b83b7cf1d95425e18729bf3d1f13fafcd712d71937891d0b` |

The exact source packet is the full selected location object and its matching
map-room object, serialized as canonical UTF-8 JSON with
`ensure_ascii=False`, `sort_keys=True`, and separators `(',', ':')`. The
tracked packet files under `source-packets/` are the exact bytes supplied to a
request; their hashes must match both this table and `staging-manifest.json`.
The tracked `expected/<scene>.json` bundles contain independently prepared
source facts, approved topology, reference coverage, and protected unknowns.
They are derived only from the same selected source objects, never from model
outputs.

Do not send any other scene packet, prior generation, M1/D1 or item-1 holdout,
owner example or derivative, known-example catalog, campaign/runtime state,
prior-play PC, unrelated module text, retrieval result, owner rating, or
internet material. Source-restricted facts may be included in the GM-aware
input only as marked in that scene's expected-fact record. They must not be
exposed in public arrival claims. The known-example catalog is only a local
leakage-screen input and is never prompt content.

The raw source packet can contain GM-guarded fields; every source fact is
audience-classified in the independent fact ledger, and public arrival claims
must exclude guarded and source-reference-only material. A preapproved abstract
`usable_space` role slot is the only non-source entity slot; it is a
Builder-authored schematic role, not a new source-world entity. No other entity
or topology node may be added.

The packet's coordinates and tactical-grid labels are schematic. They do not
establish metric distance, scale, compass bearing, door/access, traversal,
visibility, sensory range, movement cost, or legality. Use only explicitly
recorded map directions as source facts. A Builder-authored initial relation
must be labeled `builder_authored`, stay within the separately supplied
approved topology, and must not be presented as extracted. Unsupported facts
remain `unknown`; do not invent entities, topology, mechanics, or prior PCs.

## 3. Frozen prompt, output contract, and parameters

The exact system prompt, task template, JSON output contract, parameter
record, scene selection, and historical availability record are tracked under
`llm-staging-protocol/`. Runtime ledger, responses, and run artifacts remain in
the project-local staging scratch directory. Their SHA-256 values,
along with per-scene packet/expected-input hashes, this protocol hash,
client/test hashes, and offline validator hashes, are recorded in
`staging-manifest.json`. The manifest is generated only after all frozen files
exist. Do not edit a bound input without a new review and refreeze.

Packaging deviation for review: the original step (a) builder made a Context7
documentation network lookup despite the zero-network assignment. No OpenRouter
generation is reported. Strict zero-network compliance cannot be claimed for
step (a); Overseer adjudication is pending.

The model receives one scene at a time and returns one JSON object conforming
to `output-contract.schema.json`. It creates an initial fixture and a staged
arrival with exactly ordered approach, threshold, and focal segments; checkable
claims bind to structured fact IDs and provenance. Invitations preserve player
choice and do not assert success. The exact response and generated artifact
hashes are recorded after the call; no response exists during step (a). The
model receives each frozen source/fact/topology/coverage/unknown artifact as
exact stored bytes, not a re-derived serialization.

Generation parameters use temperature 1.0, top_p 1.0, frequency_penalty 0.0,
presence_penalty 0.0, max_tokens 4096, and streaming disabled. JSON-object
response format is requested and the local frozen schema remains authoritative.
Reasoning controls are not sent: the route-specific support and owner-approved
effort are unconfirmed, so the selected model's default is left unchanged. No
seed is supplied. The single requested model is
`openai/gpt-6-luna`; OpenRouter provider fallbacks are disabled. No models list,
tool, or assistant-judge request is included. Unsupported parameters, request
errors, identity mismatch, invalid output, or missing evidence consume the
scene's one attempt. Do not drop a parameter and retry.

## 4. Route, availability gate, and attempt accounting

The owner-selected route is OpenRouter with the exact model ID
`openai/gpt-6-luna`; it is not `openrouter/auto` and not the legacy
`openai/fallback` profile. Production `model_config.py` and routing remain
untouched. The returned model ID must exactly match the requested ID, and each
receipt must record the upstream provider, generation ID, and usage. Missing
identity fields or a returned-model mismatch make the scene FAIL; stop without
substitution.

The prior context-mode listing fetch on 2026-11-08 did not surface the exact
base-model entry and did not preserve raw JSON. Its verdict is
`UNCONFIRMED`; it is not an availability pass. Before generation call 1, a
single unauthenticated script-based GET of the public OpenRouter model listing
must save the raw JSON and SHA-256, then verify an exact `data[].id` match for
`openai/gpt-6-luna`. The existing owner ruling permits one read-only GET, but
the earlier fetch consumed that permission without producing the required
proof. Therefore, obtain explicit Overseer authority for a replacement GET
before running `check_model_availability.py`. If that authority is absent, the
listing is unavailable/malformed, the raw bytes or digest cannot be preserved,
or the exact ID is absent, stop before any generation call. Do not substitute
another model. The GET is an availability check, not a generation attempt; it
does not increase the three-call generation cap.

The generation cap is **exactly three attempts total**, one attempt for each
listed scene and in listed order. The other 27 attempts from the former 30-call
ceiling are not authorized. Every provider dispatch counts, including failure,
timeout, rejection, continuation, safety/moderation, tool, summary, and
validation requests. Client/router retries, redirects, provider fallbacks,
tools, and model-side continuation are disabled. Each scene is dispatched at
most once. An invalid or failed scene consumes its allocation and is never
rerun. If attempt accounting or actual model identity is uncertain, stop.

The study client uses one fixed, study-wide append-only control ledger at
`tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging/study-attempt-ledger.jsonl`.
Its location is independent of caller-selected run IDs and run roots. The first
reservation binds the approved manifest hash, execution-approval hash,
availability-attestation hash, run ID, and run-root-relative identity. Every
later client must match that binding; a different run ID or root cannot reset
the three-attempt total. Each reservation is appended under the ledger lock and
durably flushed before the injected one-shot transport is invoked. An
interrupted or unresolved reservation, malformed/corrupt ledger, or identity
mismatch fails closed and does not dispatch. Raw response bytes are preserved
within the bounded response limit when available. Missing or malformed
provider identity/usage data produces a safe failed result and a study-wide
stop marker; no exception text or response content is written to the ledger.
Per-run response and validation artifacts remain under
`runs/<run-id>/`. The existing generic provider-budget utility is not used
because its enforced root is `tmp/combat_capture` and its ledger path is scoped
to `tmp/n2`; this fixed study-wide ledger is the bounded alternative allowed
by the owner ruling. The later execution adapter must itself perform one
dispatch without hidden retries or redirects and supply the safe provider
receipt.

## 5. Independent checks and semantic review

Before any call, verify source and packet hashes, manual lineage review, exact
manifest order, prompt/schema/parameter hashes, and the availability proof.
For each returned artifact, preserve the raw response and exact artifact hash
before validation. Use the independent source-fact, topology, coverage, and
protected-unknown records; never create an expected record from model output.

Deterministic gates cover output parsing/contract, fixture contract and
provenance, the independent `validate_positional_coverage` reference,
topology and identity, unknown preservation, typed arrival claim-to-fact
bindings, exact guarded markers, and artifact hash integrity. Exact-marker
checks do not detect semantic paraphrases. The Overseer must review the complete
public arrival prose against source facts, topology, guarded knowledge, agency,
and protected unknowns. Do not construct an independent expected reference by
copying model output. In particular, do not fabricate an `arrival_reference`
from generated prose to call `arrival.validate_staged_arrival()`; that validator
requires independently bound reference segment hashes/claims and does not
certify arbitrary generated prose. Until an independently reviewed staging
claim-binding check is available for a returned artifact, that scene is
BLOCKED, not passed. The existing PR116 fixture validator does not itself
certify arbitrary LLM prose or establish semantic correctness.

No linked-view/frontage case is tested. Do not claim that it was tested or
passed. No movement, gameplay, server, Capture_Arena, port, lock, or runtime
integration is part of this study.

## 6. Review order, ratings, and outcome rules

The Overseer receives the outputs first and performs fail-closed semantic
review of prose claims and guarded-content paraphrases. The owner must not see
the outputs or rate them until the Overseer review is complete. After that
review, only the owner supplies the two ratings for each exact artifact:

- **Legibility:** how readily a reader reconstructs staged relationships and
  distinguishes source facts, Builder authorship, and unknowns.
- **Usefulness:** whether the arrival is coherent and actionable while
  preserving player agency and protected unknowns.

Use these frozen 1-5 anchors. Bind every rating to study ID, scene ID, raw
response and artifact hashes, prompt/config hash, model/provider identity, axis,
owner/rater, timestamp, integer 1-5, and a short rationale citing visible
content. Do not self-score, use a model judge, repair an artifact before rating,
or pool ratings across scenes.

| Score | Legibility: reconstruct staged relationships and distinguish provenance/unknowns |
| --- | --- |
| 1 | Scene is not reconstructable; key relations are missing, contradictory, or materially misleading. |
| 2 | Only fragments are legible; important staging or knowledge boundaries are ambiguous. |
| 3 | Main scene is recoverable, but at least one important relation or distinction remains unclear. |
| 4 | Approach, threshold, focal point, relevant extents, identities, and epistemic boundaries are readily understood without material contradiction. |
| 5 | Relevant stage is immediately clear, coherent, and economical; source facts, authored decisions, and unknowns are unmistakably distinguished. |

| Score | Usefulness: actionable, coherent arrival preserving agency and protected unknowns |
| --- | --- |
| 1 | No usable staging, or it encourages a critical false claim, leak, or unauthorized outcome. |
| 2 | Little practical help; an arrival or first interaction needs substantial reconstruction or guesswork. |
| 3 | Some useful orientation/action, but a notable staging gap or unclear affordance remains. |
| 4 | Coherent arrival and visible invitations to act; preserves unknowns and does not prescribe choice or success. |
| 5 | Especially easy to present and act within; vivid but bounded staging, coherent transition, and clear agency-preserving invitations. |

A scene is PASS only when every deterministic gate passes, the Overseer's
semantic review passes, and both owner axes are at least 4. A critical
contradiction, provenance mislabel, protected-unknown promotion, added
topology/access/metric/mechanic, public guarded leak/false trigger, fixed-anchor
relocation, prior-PC contamination, actionable prose-only claim, fabricated
sensory gradient, or prescribed player choice/success is FAIL regardless of
rating. Missing evidence, unresolved source/lineage review, diagnostic error,
identity uncertainty, or missing owner rating is BLOCKED. Study PASS requires
all three approved scenes to PASS; do not average or partially pool.

## 7. Evidence and retention

Only after step (b) is separately approved, preserve each run under
`tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging/runs/<run-id>/`.
Keep the frozen protocol and input hashes, availability raw listing and
attestation, exact source packet/fact/topology/coverage artifacts, one request
and response per approved scene, request/response/artifact hashes, safe
provider receipt/usage, timestamp, append-only attempt ledger, deterministic
diagnostics, Overseer semantic review, then owner ratings and per-scene result.
The output access order is Overseer first, owner only after semantic review.
Do not store credentials, authorization headers, or secret configuration.
The staging client stores raw provider response bytes only in the restricted
run directory and records no response text in its ledger or console output.

## 8. Remaining pre-call conditions

The owner-approved selection, model, route, fallback/retry/tool posture, exact
three-attempt cap, rating threshold, review order, and no-linked-view scope are
fixed by ruling S, item 2. Sequence step (a) is limited to this protocol,
frozen inputs, availability-check tooling, ledger wiring, and provider-free
dry-run tests. Submit this package for planner/Overseer review and stop. No
generation call is permitted until that review approves step (a), the required
replacement availability GET is explicitly authorized and confirms the exact
model ID, and all pre-call hashes/manual lineage checks agree.
