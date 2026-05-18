# Builder Prompt: Toolkit Fidelity Review UI Deadlock Fix

Implement the OpenSpec change `toolkit-fidelity-review-ui-deadlock`.

## Primary Goal

Fix the Module Toolkit accurate-ingest deadlock where a job pauses at `awaiting_review` but the GUI shows only raw JSON output and no approval controls.

## Files To Inspect First

1. `web/templates/module_toolkit.html`
   - `loadToolkitHomebrewReview(jobId)` around the advanced-mode guard
   - `renderToolkitHomebrewFidelityReview(reviewPayload)` around button rendering
   - upload polling branch for `job.status === 'awaiting_review'`
2. `web/routes/toolkit_homebrew_routes.py`
   - review POST handler
   - strict fidelity approval errors
3. `web/extensions/toolkit_homebrew_fidelity_review.py`
   - `can_approve_fidelity_review(...)`
   - payload fields: `can_approve`, `can_reject`, `refusal_reason`, `blueprint`, `blockers`
4. Existing toolkit tests, especially `scripts/test_toolkit_module_build_publication_parity.py`.

## Required Behavior

1. If a job is `awaiting_review`, review loading MUST happen even when `HOME_BREW_ADVANCED_MODE` is false.
2. If the review is approvable, show enabled `Approve Fidelity Review`, `Reject Review`, and `Refresh Review` controls.
3. If the review is not approvable, show disabled approve with a clear reason, plus enabled `Reject Review` and `Refresh Review` controls.
4. If the review payload is missing, still show disabled approve plus refresh; do not leave only raw JSON output.
5. If the job is `approved_for_build`, show `Start Build`.
6. Do not add broad force approval.
7. Backend strict approval errors must remain intact.

## Step-By-Step Implementation

1. Modify `loadToolkitHomebrewReview` to accept options:
   - Example: `async function loadToolkitHomebrewReview(jobId, options) { ... }`
   - Add `const required = Boolean(options && options.required);`
   - Change early return to `if (!HOME_BREW_ADVANCED_MODE && !required) { ... return; }`
2. Update the polling branch for `job.status === 'awaiting_review'`:
   - Change `await loadToolkitHomebrewReview(jobId);`
   - To `await loadToolkitHomebrewReview(jobId, { required: true });`
3. Update other terminal required branches if useful:
   - `approved_for_build`
   - `rejected`
   - `awaiting_overwrite_confirmation`
4. Add helper `getToolkitFidelityApproveDisabledReason(reviewPayload)`:
   - Read `reviewPayload.fidelity_review`
   - Check `refusal_reason`
   - Check status `missing`, `failed`, `blocked`
   - Check blockers length
   - Check blueprint refusal/status
   - Return fallback message
5. Add helper `renderToolkitHomebrewRequiredReviewActions(reviewPayload)`:
   - Use `homebrewFidelityReviewActions` if available
   - Do not duplicate buttons if it already contains buttons
   - Render controls based on job status and can_approve/can_start_build
   - Wire approve/reject/start-build/refresh to existing functions
6. Call fallback helper immediately after `renderToolkitHomebrewFidelityReview(review);` in `loadToolkitHomebrewReview`.
7. Change status copy in `awaiting_review` polling branch:
   - Remove misleading `Legacy Homebrew job is awaiting review`
   - Use `Homebrew job is awaiting source-fidelity review` where appropriate, or generic `Homebrew job is awaiting review`.
8. Add tests:
   - Prefer source-contract tests if no DOM harness exists.
   - Assert required mode exists and bypasses advanced-mode guard.
   - Assert awaiting_review passes required mode.
   - Assert fallback action helper exists and is called.
   - Assert disabled reason helper checks refusal/blockers/blueprint.
   - Assert backend strict error `fidelity_review_not_approvable` still exists.

## Commands

Use `.venv/bin/python` for tests.

Suggested verification:

```bash
.venv/bin/python -m py_compile scripts/test_toolkit_fidelity_review_ui_deadlock.py
.venv/bin/python -m unittest -q scripts.test_toolkit_fidelity_review_ui_deadlock
.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity
openspec validate toolkit-fidelity-review-ui-deadlock
```

If no new Python test file is needed, run the extended existing test file instead.

## Do Not Do

- Do not modify normalization or repair logic.
- Do not auto-start accurate-ingest builds after approval.
- Do not add a broad `force: true` bypass.
- Do not loosen `can_approve_fidelity_review(...)`.
- Do not remove raw JSON diagnostics; keep them supplemental.
