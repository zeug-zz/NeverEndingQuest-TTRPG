# Study 2 Provider-Free Preparation Design

## Authority and supersession boundary

The latest authority is ruling `neq-staging-study1-fail-20261109` in the
Overseer relay. It records study 1 as an envelope FAIL, not a model or Builder
quality result: three of three responses ended at 4,096 completion tokens
before staging; there is no valid artifact; semantic review is NOT APPLICABLE;
no owner ratings exist. Keep all study 1 protocol, source/expected input, and
runtime bytes unchanged. This addendum supersedes earlier execution-authority
notes only to the extent they say that study 2 provider-free step-(a)
preparation is not authorized. It does not change the 14 historical task
statuses or authorize study 1 or study 2 generation/evaluation.

## Contract decisions (MUST)

### Isolation and identity

- Keep the study 1 frozen protocol at
  `openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/llm-staging-protocol/`
  and its runtime evidence at
  `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging/`;
  both are immutable.
- Keep study 2's future protocol and preparation records separate under
  `openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/llm-staging-study2/protocol/`.
  The three planning documents are siblings at the `llm-staging-study2/`
  directory root; only future protocol payloads belong in its `protocol/`
  child.
- Use the project-relative study 2 root
  `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study2/`.
  Put each future run's artifacts under `runs/<run-id>/`; keep the one
  studywide ledger at the study 2 root, not under a run ID.
- Bind the ledger to the fixed identity
  `mise-en-scene-study2-20261109`. Run IDs, run-root selection, and repeated
  invocations MUST NOT create a fresh cap or point at the study 1 ledger. A
  missing, corrupt, or identity-mismatched ledger fails closed. A reservation
  left pending is consumed and MUST NOT be dispatched again.

### Delta-only contract and canonical input ownership

- The gate, not the model, owns the frozen canonical source packet, expected
  bundle, approved topology, and base facts. The study 2 request binds the exact
  scene ID plus topology ID/SHA-256 and expected-bundle ID/SHA-256 taken from
  the frozen study 1 manifest. It does not copy, regenerate, or rewrite those
  inputs.
- The response may contain only the exact input references and authored
  fixture deltas, stage-role bindings, claims, and arrival prose. It MUST NOT
  echo or replace topology, source facts, base facts, or the expected bundle.
- The study 2 schema MUST reject unknown keys at the root and every nested
  object. The gate MUST reject unknown IDs, stale or mismatched hashes, and any
  attempted topology/base-fact overwrite before accepting a delta.
- The deterministic gate MUST hydrate a full fixture in memory from the
  canonical inputs and validated deltas, then run ALL existing safety gates on
  that full fixture. Hydration MUST NOT write a file or mutate canonical input
  bytes. Existing provenance, protected-unknown, topology, identity,
  positional-coverage, knowledge-boundary, and arrival-prose checks remain in
  force.
- Keep the exact three scenes `ha003-i02`, `sd005-i03`, and `tsu001-ao02`, the
  OpenRouter transport, and exact model ID `openai/gpt-6-luna`. There is no
  fallback, retry, continuation, alternate model, or new scene. Linked-frontage
  is not a study 2 scene and MUST NOT be claimed as tested by this study.
- The offline stage-prose reference for each scene MUST be hand assembled from
  that scene's frozen expected inputs and source material only. It is not
  model-written and does not add owner judgments, ratings, or claims about
  study 1.

### Ledger and execution gate

- The new three-attempt allocation is studywide, separate from and never
  transferable to or reset from the exhausted study 1 ledger. An interrupted
  pending reservation consumes its slot and MUST NOT be dispatched again; no
  run ID or alternate root can recover it.
- Before any reservation, credential access, or HTTP dispatch, future execution
  MUST validate both (1) explicit owner approval for the new cap of exactly
  three attempts and (2) Overseer approval of step (a), each bound to the study
  2 identity. Missing or invalid approval MUST refuse without reserving or
  consuming any attempt. After valid approval, reserve before credential access
  and HTTP. Missing returned model/provider/generation identity or a mismatch
  after reservation consumes that attempt and stops the study. No fallback or
  retry is permitted.
- Missing, corrupt, or identity-mismatched ledger state MUST fail closed and
  MUST NOT reset the cap. These ledger failures do not authorize a fresh ledger
  or a study 1 ledger substitute.
- Step (a) is offline-only. It MUST NOT make HTTP requests, invoke a provider,
  load credentials, or enable a CLI/runtime path that bypasses the approvals.
  Tests use an injected fake transport and a zero-network tripwire only.
- No study 2 generation task is defined here. Later execution requires a new
  authority decision after the stated approvals; this plan cannot mark it
  complete or implement it.

### Availability, sizing, timeout, and cost estimate

- Reuse exactly the confirmed historical attestation
  `llm-staging-protocol/availability-check.json`: performed
  `2026-11-09T03:48:13Z`, exact ID `openai/gpt-6-luna` present, raw-listing SHA-256
  `d94d8370997bb6a32c8265d0c5368d98c121355ebed0c51698539d81e32bdc13`. The
  ruling reports 829,400 raw bytes. Preserve the attestation path, timestamp,
  and hash as provenance. Do not use the older unconfirmed Nov-08 record as
  current availability and do not issue another GET.
- For each of the three scenes, hand assemble one conformant delta-only
  reference from expected inputs/source only. Count locally using an already
  installed tokenizer package, if one is present; do not install/download a
  tokenizer or use network access. If no suitable actual tokenizer is already
  installed, use a documented local approximation and label each count
  `APPROXIMATE`.
- Let `L` be the largest of the three local reference-token estimates. Propose
  `max_tokens = 1024 * ceil((3 * L + 2048) / 1024)`, which is at least three
  times the largest estimate plus 2,048 explicit reasoning-headroom tokens,
  rounded up to a 1,024-token boundary. Do not impose a separate 2,048-token
  estimate threshold or request extra permission merely because `L` is larger.
- Propose `timeout_seconds = 60 * ceil((ceil(max_tokens / 25) + 60) / 60)`,
  using 25 generated tokens/second plus a 60-second transport/processing reserve
  and rounding up to a 60-second boundary. `max_tokens=8192` and
  `timeout_seconds=420` are illustrative only when the measured inputs make
  those formulas yield those values. Report the exact calculated proposal for
  owner cap approval; this sizing work never dispatches a call.
- The preparation report MUST provide a numeric three-scene cost estimate
  marked `ESTIMATE`, calculated from estimated input/output token counts and
  the rate fields in the one hash-verified historical raw listing. Do not treat
  the study 1 actual cost as a unit rate. If the raw listing/rate fields are
  unavailable or its hash does not match, report cost as `UNPRICED/BLOCKED`,
  make no new GET, and stop before claiming step (a) complete.
- The attestation names
  `availability-check/model-listing.json`. Planning verification confirmed
  `test -f tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging/availability-check/model-listing.json`;
  a byte-only check found 829,400 bytes and the exact SHA-256 above. No listing
  content or generated output prose was read. The future preparer MUST recheck
  this exact file's size/hash before reading its rate fields; if it is absent
  or mismatched, report `UNPRICED/BLOCKED` and make no GET.

## Guidance (SHOULD)

- Keep the delta payload minimal and scene-specific; make identity/hash
  references explicit and let Python retain authority over canonical facts.
- Keep deterministic validation independent of model output prose. A valid
  JSON shape is not a substitute for the existing safety gates.
- Preserve hash snapshots for the frozen study 1 protocol and runtime before
  and after step-(a) preparation. Compare both file sets and bytes; hash only
  generated output files and do not open or display generated output prose.

## Provider-free verification boundary

The implementation-preparation tasks require the focused staging suite, the
existing 159-test mise-en-scene prototype baseline, and the 276-test mapping
pilot suite. Added tests must run in addition to the old baseline, not replace
or narrow it. Required checks include strict unknown-key/hash/overwrite
rejections; ledger cap, pending, corrupt, missing-identity and mismatch
fail-closed cases; repeated-run/root non-reset; a zero-network tripwire;
study 1 byte-hash equality; ASCII compliance; and strict OpenSpec validation.
No test or prep task makes a provider call.
