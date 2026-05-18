# Tasks: Toolkit Fidelity Review UI Deadlock Fix

## 1. Current-State Inspection

- [x] 1.1 Inspect `web/templates/module_toolkit.html` and locate `loadToolkitHomebrewReview(jobId)`.
- [x] 1.2 Confirm the early return controlled by `HOME_BREW_ADVANCED_MODE`.
- [x] 1.3 Inspect the upload polling branch for `job.status === 'awaiting_review'`.
- [x] 1.4 Confirm that polling stops after calling `loadToolkitHomebrewReview(jobId)`.
- [x] 1.5 Inspect `renderToolkitHomebrewFidelityReview(reviewPayload)` and confirm the button rendering conditions.
- [x] 1.6 Inspect backend strict approval in `web/routes/toolkit_homebrew_routes.py` and confirm it must remain strict.

## 2. Required Review Loading

- [x] 2.1 Update `loadToolkitHomebrewReview` signature to accept an optional options object, for example `loadToolkitHomebrewReview(jobId, options)`.
- [x] 2.2 Inside the function, derive a boolean such as `const required = Boolean(options && options.required);`.
- [x] 2.3 Change the advanced-mode guard so it only returns early when `!HOME_BREW_ADVANCED_MODE && !required`.
- [x] 2.4 Preserve old optional behavior when `required` is false.
- [x] 2.5 Update the `awaiting_review` polling branch to call `await loadToolkitHomebrewReview(jobId, { required: true });`.
- [x] 2.6 Update `approved_for_build`, `rejected`, and `awaiting_overwrite_confirmation` branches if they need required review actions after polling stops.
- [x] 2.7 Do not make unrelated advanced panels visible just because review loading is required.

## 3. Required Review Action Row

- [x] 3.1 Add a helper to compute why approval is disabled, for example `getToolkitFidelityApproveDisabledReason(reviewPayload)`.
- [x] 3.2 The reason helper must check, in order: `refusal_reason`, failed/missing/blocked status, blocker count, blueprint refusal reason, blueprint status, fallback text.
- [x] 3.3 Add a helper to render fallback controls, for example `renderToolkitHomebrewRequiredReviewActions(reviewPayload)`.
- [x] 3.4 The helper must not duplicate buttons when `homebrewFidelityReviewActions` already contains buttons.
- [x] 3.5 When `job_status === 'awaiting_review'` and `can_approve === true`, render enabled `Approve Fidelity Review`, enabled `Reject Review`, and enabled `Refresh Review` controls.
- [x] 3.6 When `job_status === 'awaiting_review'` and `can_approve !== true`, render disabled `Approve Fidelity Review`, enabled `Reject Review`, enabled `Refresh Review`, and visible disabled reason text.
- [x] 3.7 When `fidelity_review` is missing but job is `awaiting_review`, render disabled approve with `Fidelity review details are unavailable. Refresh review details or reject this upload.`.
- [x] 3.8 When `job_status === 'approved_for_build'`, render or preserve enabled `Start Build` and `Refresh Review` controls.
- [x] 3.9 Wire fallback buttons to existing functions: `submitToolkitHomebrewReviewDecision(jobId, 'approve')`, `submitToolkitHomebrewReviewDecision(jobId, 'reject')`, and `loadToolkitHomebrewReview(jobId, { required: true })`.
- [x] 3.10 Ensure fallback controls use existing escaped HTML helpers or safe DOM construction.

## 4. Fidelity Panel Button Behavior

- [x] 4.1 Keep the normal `Approve Fidelity Review` button enabled only when `review.can_approve` is true.
- [x] 4.2 If `review.can_approve` is false, do not silently omit all controls; rely on the required action row to show disabled approve plus reject/refresh.
- [x] 4.3 Confirm `Reject Review` is rendered whenever `review.can_reject !== false`.
- [x] 4.4 Confirm `Start Build` is rendered when top-level `reviewPayload.can_start_build` is true.
- [x] 4.5 Confirm no broad `force approve` backend bypass is added.

## 5. Status Copy Cleanup

- [x] 5.1 Replace misleading `Legacy Homebrew job is awaiting review` copy in the `awaiting_review` polling branch.
- [x] 5.2 Use `Homebrew job is awaiting source-fidelity review` when accurate-ingest review evidence is present or fidelity mode is `accurate_ingest`.
- [x] 5.3 Use generic `Homebrew job is awaiting review` when the mode is unknown.
- [x] 5.4 Keep the JSON payload visible for diagnostics, but ensure it is not the only review surface.

## 6. Backend Contract Preservation

- [x] 6.1 Do not remove `fidelity_review_state_missing` handling.
- [x] 6.2 Do not remove `fidelity_review_stale` handling.
- [x] 6.3 Do not remove `fidelity_review_not_approvable` handling.
- [x] 6.4 Do not change `can_approve_fidelity_review(...)` to allow blockers, failed/missing/blocked status, or unready blueprint approval.
- [x] 6.5 If any backend payload additions are needed, keep them additive and backward-compatible.

## 7. Regression Tests

- [x] 7.1 Add source-contract test that `loadToolkitHomebrewReview` accepts an options/required argument.
- [x] 7.2 Add source-contract test that the advanced-mode guard includes `!required` or equivalent.
- [x] 7.3 Add source-contract test that `awaiting_review` calls `loadToolkitHomebrewReview(jobId, { required: true })` or equivalent.
- [x] 7.4 Add source-contract test that required review action fallback helper exists and is invoked after `renderToolkitHomebrewFidelityReview(review)`.
- [x] 7.5 Add source-contract test that disabled approve reason logic checks `refusal_reason`, blockers, and blueprint status/refusal.
- [x] 7.6 Add source-contract test that the old misleading exact string `Legacy Homebrew job is awaiting review` is not used for the awaiting-review message.
- [x] 7.7 Add source-contract test that backend strict rejection string `fidelity_review_not_approvable` still exists in `web/routes/toolkit_homebrew_routes.py`.
- [x] 7.8 Source-contract coverage sufficient. No DOM/browser smoke was run (no existing JS extraction pipeline available). Source-contract tests verify structural correctness.

## 8. Verification

- [x] 8.1 No `node --check` pipeline exists for inline template JS. Source-contract tests provide coverage. Not run.
- [x] 8.2 Run `.venv/bin/python -m py_compile` for any modified Python test files.
- [x] 8.3 Run the new or extended test file — 7 new tests in `test_toolkit_module_build_publication_parity`.
- [x] 8.4 Run existing parity tests: 49/49 pass.
- [x] 8.5 Run `openspec validate toolkit-fidelity-review-ui-deadlock` — valid.
- [x] 8.6 Manual smoke: cannot verify browser GUI directly. Source-contract tests lock the deadlock fix. Manual smoke requires a running toolkit server with an accurate-ingest upload that reaches `awaiting_review`.

## Builder Notes

- Keep changes minimal and local.
- Prefer frontend deadlock fix over backend policy changes.
- Do not add a broad override path.
- Keep disabled approve visible and explanatory; do not make a user infer policy from raw JSON.
- Use `.venv/bin/python` for repository test commands.
- Preserve ASCII-only source text.
