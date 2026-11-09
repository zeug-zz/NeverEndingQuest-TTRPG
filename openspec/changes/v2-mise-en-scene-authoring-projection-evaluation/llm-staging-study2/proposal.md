# Study 2 Provider-Free Preparation Proposal

## Authority and historical boundary

The authoritative ruling is `neq-staging-study1-fail-20261109` in
`/Users/zeug/Projects/NeverEndingQuest/.git/overseer-relay/campaigns/neq-current-build/rulings/B.md`.
Study 1 remains a frozen FAIL: all three responses ended with
`finish_reason=length` at 4,096 completion tokens before arrival staging, so no
valid artifact exists. Semantic review is NOT APPLICABLE and there are no owner
ratings. Its protocol, source inputs, expected inputs, and runtime evidence are
historical and immutable.

That ruling authorizes only provider-free preparation of study 2 step (a) on
draft PR127, followed by review and a stop. It does not authorize a generation
call. Study 2 execution remains disabled until the owner approves a new,
studywide cap of exactly three attempts and the Overseer reviews step (a).

## Problem and objective

Study 1 tested an envelope that echoed canonical topology and fixture content
already held by the deterministic gates. The envelope exhausted its token
limit before emitting staging, so it supplies no evidence about staging
quality. Prepare a smaller, hash-bound delta contract that retains every
existing safety check without asking the model to reproduce canonical inputs.

## Scope

- **MUST:** Keep this within the existing
  `tt-mise-en-scene-authoring-projection` capability. Prepare a distinct study 2
  protocol, artifacts, run root, and fixed studywide ledger identity. Preserve
  the study 1 protocol and runtime bytes.
- **MUST:** Bind the response to the canonical topology and expected bundle by
  their existing IDs and SHA-256 values. Emit only authored fixture deltas,
  stage-role bindings, claims, and arrival prose. The gate retains the canonical
  inputs and reconstructs the full fixture deterministically in memory for all
  existing safety gates.
- **MUST:** Retain exactly `ha003-i02`, `sd005-i03`, and `tsu001-ao02`, the
  OpenRouter transport, model `openai/gpt-6-luna`, no fallback, and no retries.
  Preparation itself makes no network or provider calls.
- **MUST:** Keep future execution disabled until both required approvals are
  recorded. Do not add an execution task to this preparation plan.
- **SHOULD:** Use the historical, hash-verified availability record only for
  provenance and any rate-based estimate. Do not repeat the availability GET.

## Non-goals

No study 2 model generation, owner rating, semantic review, live evaluation,
new availability GET, study 1 rerun, study 1 ledger reuse/reset, changes to
frozen study 1 inputs or artifacts, added linked-frontage scene, production
runtime behavior, or implementation in this planning amendment. This proposal
does not turn any estimate or study 1 observation into an owner judgment.

## Smallest capability set

- Existing `tt-mise-en-scene-authoring-projection`: the preparation contract
  extends this capability's offline fixture and evaluation seam; no second
  capability or spec file is needed.
