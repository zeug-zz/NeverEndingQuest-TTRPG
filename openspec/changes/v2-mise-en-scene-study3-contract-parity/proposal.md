# Proposal

## Why

Study 2 exposed undisclosed output-facing validator rules, and Study 3 now has a provider-free parity contract but no isolated durable runner. The approved three-scene experiment needs reservation-before-dispatch, fail-closed accounting, and the exact approved envelope without changing or consuming frozen Study 1/2 state.

Authority: `neq-study2-fail-adjudicated-20261110`, `neq-standing-authority-20261110`, `neq-study3-pre-approved-20261110`, `neq-study3-apply-20261110`, and `neq-s-study3-runner-revision-20261111`.

## What Changes

- Preserve the existing Study 3 parity contract, reference fixtures, diagnostic findings, protocol pins, and all completed task IDs, checkboxes, and evidence. Do not repair or re-evaluate Study 1/2, or alter their protocol, implementation, frozen evidence, original failures, or verdicts.
- Add a Study 3-isolated durable attempt and cost ledger plus a one-shot runner. Reservations must be durable before credential lookup or dispatch, bind the fixed Study 3 identity and exact ordered scene/request, and fail closed on unsafe, duplicate, pending, corrupt, concurrent, or restarted state.
- Reuse the reservation-gated OpenRouter dispatch and response-sanitization mechanism from commit `008cc4d4` through a Study 3-local policy adapter. Keep legacy Study 1/2 code and pins unchanged while enforcing the Study 3 envelope: OpenRouter `openai/gpt-6-luna`, `allow_fallbacks=false`, exactly one POST per scene, no retry/rerun/redirect/stream/continuation/tools, `max_tokens=16384`, and a 720-second timeout. Do not perform another availability GET.
- Add provider-free tests for reservation ordering, no second attempt, confinement/symlinks/traversal, duplicate/pending/corrupt/restart/concurrency behavior, cost-budget refusal and reconciliation, and credential/output privacy. Historical expected and conservative costs remain estimates (about USD 0.01 and USD 0.03); the hard ceiling is USD 0.05.
- Conditional execution is pre-authorized for the primary only after all 11 required CI checks pass on the exact published SHA and a provider-free preflight on that same SHA has zero infrastructure failures. No additional per-step approval is required after those gates. Stop on identity/transport/non-200 failure with later attempts unspent; an HTTP 200 with invalid content consumes that scene and may continue only when actual cost is reconciled and budget remains safe. Stop after the run for independent semantic review; do not self-score or expose output prose in status reports.
- Keep raw outputs and the ledger private under the project-relative Study 3 root `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study3-prep/`. Do not modify the existing preliminary report or any other report.

## Current Status

Tasks 1.1-4.1 and their existing evidence remain unchanged. This revision changes planning only: the new ledger, runner, tests, final exact-SHA preflight, publication, and primary-owned execution tasks remain unchecked. No code, provider call, allocation, or report was changed in this planning update. Execution remains gated on exact-head green CI and the zero-infrastructure-failure provider-free preflight; independent post-study semantic review remains required.

## Capabilities

### New Capabilities

None. This work continues the existing capability and does not create a parallel staging capability.

### Modified Capabilities

- `tt-mise-en-scene-authoring-projection`: add the Study 3 durable-runner, isolated accounting, conditional execution, and output-privacy contract to the existing parity, reference, and preparation-isolation requirements.

## Impact

The approved implementation adds only an isolated Study 3 runner/ledger and provider-free tests under the Study 3 namespace, then conditionally runs the already-approved experiment after the exact-SHA gates. Study 1/2 code, frozen protocols/evidence, protocol pins, and reports remain untouched. Existing parity, diagnostics, fixed scenes/order/identity, and historical rate provenance remain bound; no additional availability request or shared gameplay path is introduced. Git publication is DRAFT-only and merge is not authorized.
