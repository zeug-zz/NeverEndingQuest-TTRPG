# LLM Builder Mise-en-Scene Staging Study Protocol

**Status: DRAFT / UNFROZEN / NOT OWNER-APPROVED / NO PROVIDER CALLS AUTHORIZED.**

This draft addresses the separately authorized planning item for an LLM Builder
staging study. It is not the offline fixture study, the Section 2 holdout
evaluation, a production acceptance test, or permission to call a provider. The
owner must approve the exact protocol, model/route, and cap before any call.
No source selection, prompt, route, call allocation, rubric threshold, or result
is final here.

## 1. Question and limits

Can one LLM Builder produce a useful initial scene fixture and staged arrival
from a small, approved, fact-bound source packet without changing source truth,
inventing topology, promoting unknowns, or leaking guarded material?

This is a small, exploratory authoring study. A positive result would apply only
to the exact approved source packets, prompt, model route, and outputs reviewed.
It would not prove general LLM Builder capability, select a production format,
approve module backfill, establish runtime behavior, or supersede any existing
M1/D1, SP3/SP3b, owner, or live-capture evidence. It does not use the proposed
R8 advisory budget or R9 gameplay budget.

The proposed output per scene is one machine-readable initial scene fixture
including a structured relationship layer and a Builder-authored staged-arrival
description. It is not four-condition A/B/C/D scoring. Any local deterministic
projection used below is diagnostic only; it is not another model call or a
condition comparison.

## 2. Provisional scene candidates and source provenance

Four candidates are proposed in `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging/scenes.json`.
They are entries in `modules/published_modules.json`; their exact source files,
source packets, hashes, token fingerprints, and all 4 x 31 pair results are in
that JSON. The packet used for each fingerprint is the canonical UTF-8 JSON
serialization of exactly the full selected `locations[locationId=...]` object
and its matching `map.rooms[id=...]` object. Serialization uses
`ensure_ascii=False`, `sort_keys=True`, and separators `(',', ':')`. The JSON
records both the full source-file SHA-256 and the exact packet SHA-256.

| Proposed scene ID | Source location | Source file SHA-256 | Packet SHA-256 | Screen disposition |
| --- | --- | --- | --- | --- |
| `into_the_deepvault:scene:ha003-i02` | `Into_the_Deepvault / HA003 / I02 - Ironbound Soul Cells` | `b90e6348d361d2978103af88a2b9b6b064f0a7d759b001585b7227e7c327a159` | `165d983bc572ba2f900a69bbb893e4f76222b2ca5e1923f0b4bea4693fd26f3e` | No exact or threshold review match in 31 bounded pairs; manual lineage review still required. |
| `into_the_deepvault:scene:sd005-i03` | `Into_the_Deepvault / SD005 / I03 - Hall of Echoing Stone` | `d625edb639b9ee935709afdc39a31f5929db52699b3ee14d819202da80adbb9a` | `628b1d68a7d2dd5ab441e20cc031b58c7ee6fedb7ad466a6eaad175214a4a6ee` | No exact or threshold review match in 31 bounded pairs; manual lineage review still required. |
| `xhalruuns_masquerade:scene:tsu001-ao02` | `Xhalruuns_Masquerade / TSU001 / AO02 - Veilsplit Threshold` | `1f77e3c4598efddf0db3f9a6f52015b98e00f03f4a37fe2e91882813e4a97b2d` | `2a44cebcc17617e5b83b7cf1d95425e18729bf3d1f13fafcd712d71937891d0b` | No exact or threshold review match in 31 bounded pairs; manual lineage review still required. |
| `murder_at_the_drowning_lass:scene:rme001-h03` | `Murder_at_the_Drowning_Lass / RME001 / H03 - Duskmire Hollow` | `eab1cee44c5a45ea95ba8783ae2f8e118218c12af2a4aeaac56837068c9ee1b2` | `1a9b1f2c91a60b2ab88e0c37304fb5a281ae95a4ba7e3378e720d82c819f5a6c` | `REVIEW_REQUIRED` for two item-1 layout pairs sharing `approach`; neither pair is rejected. Do not call on this candidate until owner/manual adjudication clears or replaces it. |

The candidates do not reuse any of the six item-1 scene identities. They are
not in the three D1 source modules (`Keep_of_Doom`, `The_Thornwood_Watch`, or
`The_Pumpkin_Kings_Curse`) and are not any of the known M1/D1 location records
or the nine owner-example records. `A_Pottsfield_Burial` and
`Night_of_the_Restless_Dead` are not proposed because the existing selection
review noted plausible Pumpkin King lineage/cross-reference concerns. Three
candidates are in modules also represented by an item-1 scene, but they are
different source locations and areas; same-module proximity is disclosed, not
treated as proof of independence. Manual source/lineage review remains a
precondition for every candidate. If any candidate is a derivative of an M1/D1
location or owner example, exclude it and rerun the full screen for its
replacement.

The lexical run used `scripts/mise_en_scene/evaluation.py`:
`fingerprint_source_text()` and `_make_pair_check()`. The pinned inputs are the
25-record development catalog (`known_examples.json`, canonical catalog SHA-256
`7defa824776c8a08dd5c2669148563680d08bd466bfb45483825703bb1634165`) plus the
six item-1 source records in `holdout-draft/manifest.draft.json` (file SHA-256
`835d1c2bd2daf9c314ff80fb665ece325cd393e4008ae15a56573cf97a6c17e2`). The
catalog file SHA-256 is
`f441cc1da547a85e0055e5edacda4ddafba13ec9a9bc17a28cab60a3d119545c`; the
helper file SHA-256 is
`7e2cd50962dd24db5806cffaa32a79304c65cea7cd75938fe3f45e78d24dbf67`.
The 124 source/derivative comparisons produced 122
`NO_MATCH_WITHIN_BOUNDED_CHECKS`, two `REVIEW_REQUIRED`, and zero `REJECT`.
The only review pairs are the two noted for Duskmire Hollow. Exact identities,
references, hashes, and declared ancestry did not match. Thresholds were not
changed. The exact matrix and flags are in `scenes.json`.

This is a bounded lexical screen, not semantic derivative detection or a
leakage certification. It screened source packets only: no LLM output exists,
so artifact-text overlap is not yet assessed. After any separately approved
call, rerun the helper over each actual output against all 31 records with its
artifact text populated; any exact/declared ancestry match is rejected and any
overlap flag requires review. Keep all source and output comparisons; do not
silently discard flagged pairs or tune thresholds.

## 3. Approved-source-only prompt provenance

The only permitted world-material seed is the exact owner-approved packet for
the selected scene: its source location object and matching map-room object,
identified by the two JSON pointers, source file hash, and packet hash in
`scenes.json`. A human-prepared source-fact ledger and independently prepared
approved-topology/reference-coverage objects may be derived only from those
same source records. Each source-extracted claim cites a supplied pointer that
was actually consulted. Source references are not permitted on Builder-authored
claims unless that cited material actually supports the claim.

Do not provide the model with M1 artifacts, D1 locations, any of the nine owner
examples or their derivatives, any item-1 holdout artifact, this study's other
scene packets or outputs, prior generations, campaign/runtime state, prior-play
PCs, unrelated module text, owner ratings, retrieval results, or internet
material. The known-example catalog is used only by the local leakage screen,
never as model prompt content. If additional seed material is needed, stop for
owner approval and hash it before use.

The prompt must label source and audience boundaries. GM/guarded source facts
may be available to the Builder only when needed to author the GM-aware fixture;
they must not enter public arrival claims. Explicit map directions may be
treated as source facts only where present in the approved source record.
Coordinates and schematic cells do not establish distance, scale, bearing,
access, doors, visibility, traversal, movement cost, sensory reach, or
mechanical legality. Conflicting source/topology claims block the case for
human resolution; the model may not resolve them by invention.

The following is a prompt skeleton, not a runnable prompt. Its hash is
`23f76ea1e26fe53084283f3ad03b32087a19965169f50b9699ac0586112d8fcc`. The hash
covers the exact UTF-8 bytes of the fenced block body below, using LF line
endings and a final LF, excluding the Markdown fence markers.

```text
You are the NeverEndingQuest (NEQ) initial-scene Builder in a separately authorized offline study.
Create one initial scene fixture and staged arrival for the supplied scene. Do not create a module, edit or persist runtime state, or describe prior-play PCs.
Inputs are limited to:
- APPROVED_SOURCE_PACKET: {{SOURCE_PACKET}}
- APPROVED_TOPOLOGY: {{TOPOLOGY_PACKET}}
- SOURCE_FACT_LEDGER: {{SOURCE_FACT_LEDGER}}
- REFERENCE_COVERAGE: {{REFERENCE_COVERAGE}}
- OUTPUT_CONTRACT: {{OUTPUT_CONTRACT}}
Treat the supplied topology and source fact ledger as authority. Do not add a node, edge, door, access, direction, distance, scale, visibility, sensory reach, movement, or mechanic from adjacency, coordinates, schematic cells, genre knowledge, or inference. Preserve a fact not established in the ledger as unknown; use explicit source_extracted, builder_authored, and unknown provenance. Cite only supplied source references, and only on claims actually supported by those references. A Builder-authored initial relation must be labeled builder_authored and stay within approved topology; it must not be relabeled as extracted.
Separate fixed anchors from mobile occupants; do not invent inhabitants. Do not place prior runtime PCs in the scene. Keep source-restricted/GM knowledge out of public arrival prose. Use only supported sensory cues; preserve unknown and not_applicable states. Stage the arrival as approach -> threshold -> focal point. Bind every checkable prose claim to its structured fact ID and provenance. A visible affordance may invite an action but must not prescribe a player choice or assert success.
Return exactly one JSON value conforming to OUTPUT_CONTRACT. Include typed arrival claim spans and provenance bindings. Do not include commentary, markdown, or extra facts.
```

Before any authorized call, freeze separate SHA-256 bindings for the exact
system/task prompt, output contract/schema, source packet, topology/reference
coverage, source-fact ledger, deterministic validator version, model/version,
provider route, generation parameters, and this protocol. The skeleton hash
does not stand in for these final hashes. No retrieval, tools, fallback model,
hidden retry, or assistant-judge prompt is permitted unless explicitly
approved and counted in the budget.

## 4. Candidate routes and call budget

No model or route is selected. Read-only candidates from `model_config.py` are:

| Candidate | Current configuration evidence | Trade-off |
| --- | --- | --- |
| `openrouter/auto` via the `production-auto` profile | Current active profile; downstream model is selected by OpenRouter. | Not preferred for a controlled study unless the actual downstream model is pinned and reported for every call; auto-routing weakens reproducibility. |
| `openai/fallback` profile with model label `gpt-6-luna` | Explicit profile in `MODEL_PROFILES`; `LLM_PROVIDER` is currently `openrouter`. | Candidate for a stable model identity only after the owner verifies the actual provider/endpoint route, availability, retention terms, and that no fallback changes identity. No code/config edit is authorized. |

These are options, not recommendations to call or proof that either route is
available. The owner chooses the exact provider, endpoint, model/version,
serving route, privacy/retention terms, and generation settings. Do not use a
dynamic route if the actual model identity cannot be recorded. Do not change
`model_config.py` or runtime routing for this draft.

The hard ceiling requested for owner consideration is **at most 30 provider
calls total**, separate from every other assessment or gameplay budget. This
draft's conservative allocation is one initial generation attempt per selected
scene: four calls if four candidates are approved or a replacement is selected;
three calls only if the owner approves a three-scene set. The remaining calls up to 30 are unallocated,
not an implicit reserve or permission to spend. The owner must approve the exact
cap and allocation; a lower cap is valid.

Count fail-closed: every provider request counts, including successful,
failed, timed-out, rejected, fallback, retry, continuation, moderation/safety,
tool, summary, and validation-model requests. One client call that produces
multiple provider attempts consumes each attempt. Disable automatic retries,
fallback, tools, and model-side continuation. If the effective route or attempt
count cannot be observed reliably, stop before calling. A failed or invalid
scene consumes its attempt and is not regenerated; no content-failure reruns.
Any need for a second attempt requires new owner approval before it occurs.
Local deterministic checks and owner ratings make no provider calls. Stop
immediately when the cap is reached or accounting becomes uncertain.

## 5. Future execution and deterministic gates

No execution occurs under this draft. If later approved, prepare one independent
stateless case per scene, in a frozen owner-approved order. Build an independent
source-fact ledger, approved topology, guarded/public knowledge reference,
required positional coverage, and protected-unknown list before the call; none
may be generated from the model output. Exclude prior runtime PCs and do not
copy them into initial authorship. Do not start a server, Capture_Arena, or live
gameplay gate.

Run the existing PR116 offline diagnostics on every returned artifact, using
the independently supplied reference objects and only the exact consulted
source references:

1. Parse the output and call `validate_fixture()` for the fixture contract,
qualified identities, reference membership, provenance classes, orientation,
and topology frame. A source-extracted fact must cite an approved source; an
unsupported fact must remain `unknown` or be explicitly `builder_authored`.
2. Call `validate_positional_coverage()` against the separately prepared
reference expectations for approach-to-threshold, threshold-to-focal,
multi-cell path/terrain/boundary extents, and usable space. The model cannot
waive a missing obligation. Mark only genuinely non-applicable items with an
independent reason.
3. Call `validate_staged_arrival()` for ordered approach -> threshold -> focal
staging, fixed-anchor/topology preservation, typed claim spans bound to the
same fact IDs and provenance, known/unknown/non-applicable sensory cues,
valid next-section transition, guarded-content boundary, and non-prescriptive
action invitations.
4. Use `trace_fact_lineage()` with independent expectations to check supported
source facts and protected unknowns across source, extraction, authorship, and
the actual deterministic A/B/C/D render bindings if those renders are built
for diagnosis. Such local renders do not create A/B/C/D study arms or owner
comparisons. Verify actual content against independently approved hashes.
5. Run `diagnose_guarded_content()` against the public arrival render using
protected markers from the independent reference. Its exact-marker scan is a
necessary check, not semantic leak detection; a human must still review
paraphrases and audience boundaries.
6. If a candidate actually uses linked views, call
`identity.validate_linked_views()` against its independent identity/frontage
reference. Do not infer doors or traversal from frontages. Movement validation
is not part of initial authorship; if a separately approved movement fixture
is added, use `identity.validate_occupant_movement()` and keep it outside this
study's current scope.
7. Normalize and preserve diagnostics with `normalize_diagnostics()`, including
stable code, layer, relation, path, and severity. Do not repair or rewrite a
failed model artifact silently.

The PR116 prototype validates supplied structured records and typed claim spans;
it is not general NLP and does not discover every unsupported natural-language
claim. Exact text hashes and exact protected-marker checks do not establish
semantic equivalence. A reviewer must check the complete arrival prose against
the source-fact ledger, topology, and guarded knowledge reference. If that
human review is unavailable, the case is BLOCKED rather than passed.

**Hard-gate outcomes:** any critical contradiction, source/provenance
mislabeling, protected-unknown promotion, added topology/access/metric/mechanic,
public guarded leak or false trigger, fixed-anchor relocation, prior-PC
contamination, actionable prose-only claim, fabricated sensory gradient, or
prescribed player choice/success is a scene FAIL. Missing source/reference,
unresolved lexical or ancestry review, missing output/hash/receipt, diagnostic
error, or missing owner rating is BLOCKED. Neither state can be hidden by
averaging. A zero-diagnostic result is not a semantic correctness proof.

## 6. Owner-only artifact rating and decision rules

Only the owner supplies ratings. No author self-score, assistant score, model
judge, or advisory assessor substitutes for an owner judgment. Rate the exact
returned scene artifact after binding its raw response SHA-256 and canonical
artifact SHA-256. Each record must include study ID, scene ID, exact artifact
hash, prompt/config hash, model/provider identity, axis, owner/rater identity,
timestamp, integer score 1-5, and a short rationale citing visible artifact
content. Rate the artifact shown; do not repair it or infer omitted facts from
other cases or source material. Deterministic source-fidelity gates are reported
separately from these subjective ratings.

**Legibility:** how readily a reader can reconstruct the staged relationships
and distinguish source facts, Builder-authored initial facts, and unknowns.

| Score | Anchor |
| --- | --- |
| 1 | The scene is not reconstructable; key relations are missing, contradictory, or materially misleading. |
| 2 | Only fragments are legible; important staging or knowledge boundaries are ambiguous. |
| 3 | The main scene is recoverable, but at least one important relation or distinction remains unclear. |
| 4 | Approach, threshold, focal point, relevant extents, identities, and epistemic boundaries are readily understood without material contradiction. |
| 5 | The relevant stage is immediately clear, coherent, and economical; source facts, authored decisions, and unknowns are unmistakably distinguished. |

**Usefulness:** whether the artifact supports an actionable, coherent arrival
while preserving player agency and protected unknowns.

| Score | Anchor |
| --- | --- |
| 1 | No usable staging, or it encourages a critical false claim, leak, or unauthorized outcome. |
| 2 | Little practical help; an arrival or first interaction needs substantial reconstruction or guesswork. |
| 3 | Some useful orientation/action, but a notable staging gap or unclear affordance remains. |
| 4 | Coherent arrival and visible invitations to act; preserves unknowns and does not prescribe choice or success. |
| 5 | Especially easy to present and act within; vivid but bounded staging, coherent transition, and clear agency-preserving invitations. |

Proposed decision rule, pending owner ratification: a scene can be a candidate
PASS only if all required deterministic gates pass, the independent semantic
review passes, all leakage/source-lineage reviews are resolved, and the owner
rates both axes at 4 or 5. Any critical failure is FAIL regardless of rating.
Missing evidence is BLOCKED. The study has a candidate-level PASS only if every
approved scene passes; do not pool scenes or hide a failing case in an average.
This small one-attempt-per-scene study cannot estimate model reliability or
support broad generalization. The 4/5 rule and all decision labels remain
unapproved.

## 7. Evidence plan

Only after explicit approval, preserve per-run evidence beneath
`tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging/runs/<run-id>/`:

- frozen protocol, source packet, topology, fact ledger, reference coverage,
  prompt, schema, validator, model/route, parameter, and owner-order hashes;
- candidate identity and source references; the pre-call pair screen and its
  manual lineage/review rulings;
- one request/response per approved scene, exact raw response and artifact
  hashes, model-reported identity, provider receipt/usage, timestamp, and
  fail-closed call-ledger entry;
- deterministic diagnostic output and any owner semantic review findings;
- owner ratings bound to exact artifact hashes and their rationales; and
- per-scene FAIL/BLOCKED/PASS outcome plus explicit missing-evidence reasons.

Never record credentials, authorization headers, or secret configuration. The
owner must approve the retention/access treatment before any raw prompt or
response is stored. No run directory or response exists in this provider-free
draft.

## 8. Open owner decisions before any call

1. Approve, replace, or reject the four provisional source scenes; resolve the
   two `approach` layout review pairs for Duskmire Hollow; confirm no candidate
   is a semantic derivative; and decide whether two scenes from
   `Into_the_Deepvault` are acceptable. Replacements require a full rerun of the
   31-pair source screen.
2. Select the exact provider, endpoint/route, model/version, actual model
   identity policy, privacy/retention terms, and whether fallback is prohibited
   (recommended: prohibit it).
3. Approve an exact cap and allocation. This draft proposes four initial calls
   at most and leaves the rest of the 30-call ceiling unallocated; the cap is
   not a target and no call is authorized now.
4. Approve or revise the prompt skeleton/hash, final exact prompt, output
   contract, generation parameters, and independent reference/expected-fact
   hashes.
5. Approve the owner rater, rating visibility and storage policy, score
   anchors, and whether both axes must be at least 4 for each scene.
6. Decide whether linked-view/frontage coverage is required. These candidates
   do not establish a linked-view/frontage test; no result may claim that case
   was tested unless a separately screened candidate/reference is added.
7. Confirm the human semantic-review owner and fail-closed review workflow for
   prose claims and guarded-content paraphrases.

Until these decisions are explicit and the exact protocol, model/route, and cap
are approved, the permitted activity is this provider-free draft and its local
source fingerprint record only. No provider or LLM call is authorized.
