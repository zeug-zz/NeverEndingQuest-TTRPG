## Overview

This change fixes a deadlock in the accurate-ingest fidelity review UI. The current code treats the review detail panel as advanced UI, but `awaiting_review` is a required workflow state. Required workflow actions must not be hidden behind `HOME_BREW_ADVANCED_MODE`.

The implementation should keep backend source-fidelity enforcement strict and make the frontend reliably actionable.

## Current State

Relevant frontend paths in `web/templates/module_toolkit.html`:

- `loadToolkitHomebrewReview(jobId)` returns immediately when `HOME_BREW_ADVANCED_MODE` is false.
- The polling handler for `job.status === 'awaiting_review'` renders raw JSON, calls `loadToolkitHomebrewReview(jobId)`, then stops polling.
- `renderToolkitHomebrewFidelityReview(reviewPayload)` renders action buttons only inside `#homebrew-fidelity-review-panel`.
- `Approve Fidelity Review` only appears when `review.can_approve` is truthy.
- `Reject Review` appears when `review.can_reject !== false`, but only if the fidelity panel renders.

Relevant backend paths:

- `web/routes/toolkit_homebrew_routes.py` sets accurate-ingest jobs to `awaiting_review` and exposes review details through `/api/toolkit/homebrew/jobs/<job_id>/review`.
- `web/extensions/toolkit_homebrew_fidelity_review.py` computes `can_approve` through `can_approve_fidelity_review(...)`.
- Backend approval currently fails closed when `can_approve_fidelity_review(...)` returns false.

## Decisions

### Decision 1: Required review UI bypasses advanced-mode hiding

`HOME_BREW_ADVANCED_MODE` may continue to hide optional advanced panels, but it SHALL NOT hide the review action surface for a job in `awaiting_review`, `approved_for_build`, `rejected`, or `awaiting_overwrite_confirmation`.

Implementation guidance:

1. Modify `loadToolkitHomebrewReview(jobId, options)` to accept an option such as `{ required: true }` or `{ forceVisible: true }`.
2. Keep existing behavior for optional manual review loading when no required workflow state is active.
3. When the polling handler detects `awaiting_review`, call `loadToolkitHomebrewReview(jobId, { required: true })`.
4. If advanced mode is disabled and `required` is true, skip the early return and load/render review details.

### Decision 2: Action row always exists for awaiting review

The UI SHALL render a review action row for `awaiting_review` even if the fidelity payload is missing, stale, or not approvable.

Action rules:

| State | Approve Button | Reject Button | Refresh Button | Start Build Button |
|---|---|---|---|---|
| `awaiting_review`, approvable | enabled | enabled | enabled | hidden |
| `awaiting_review`, not approvable | disabled with reason | enabled | enabled | hidden |
| `awaiting_review`, fidelity payload missing | disabled with missing-state reason | enabled if endpoint supports reject | enabled | hidden |
| `approved_for_build` | hidden | hidden | enabled | enabled |
| `rejected` | hidden | hidden | enabled | hidden |

Implementation guidance:

1. Keep `renderToolkitHomebrewFidelityReview(reviewPayload)` responsible for accurate-ingest details.
2. Add a small helper, for example `renderToolkitHomebrewReviewActions(reviewPayload)`, that can render fallback controls outside the fidelity panel when needed.
3. Ensure this helper is called after `renderToolkitHomebrewFidelityReview(...)`.
4. The helper MUST detect whether `#homebrew-fidelity-review-actions` already contains buttons. If it does, do not duplicate buttons.
5. If there are no buttons and `job_status === 'awaiting_review'`, render fallback controls using top-level `reviewPayload` plus `reviewPayload.fidelity_review` if present.

### Decision 3: Strict approval remains backend-authoritative

The frontend may show disabled states and helpful explanations, but the backend remains the source of truth for whether approval is allowed.

Do not add a broad override path in this change.

Backend behavior to preserve:

1. Missing fidelity signatures still return `fidelity_review_state_missing`.
2. Stale blocker signatures still return `fidelity_review_stale`.
3. Non-approvable fidelity payload still returns `fidelity_review_not_approvable`.
4. `can_approve_fidelity_review(...)` continues to reject `missing`, `failed`, `blocked`, blockers present, and blueprint not ready.

### Decision 4: Disabled approve must explain why

When approval is not allowed, the UI SHALL show a short reason near the disabled button. The reason should be composed from existing fields, in this priority order:

1. `fidelity_review.refusal_reason`
2. `fidelity_review.status` when status is `missing`, `failed`, or `blocked`
3. `fidelity_review.blockers.length` when blockers exist
4. `fidelity_review.blueprint.refusal_reason`
5. `fidelity_review.blueprint.status` when not `ready`
6. fallback: `Review is not currently approvable. Refresh review details or reject this upload.`

The reason text MUST be HTML-escaped.

### Decision 5: Status copy should be accurate

The `awaiting_review` polling copy currently says `Legacy Homebrew job is awaiting review`. That is misleading for accurate-ingest jobs.

Replace it with copy that reflects the current route:

- Accurate ingest: `Homebrew job is awaiting source-fidelity review [routing: ...]`
- Legacy review: `Homebrew job is awaiting review [routing: ...]`

The copy can be selected from `job.result.fidelity_review.mode`, `job.review_snapshot.fidelity_review.mode`, or a safe generic fallback.

## Implementation Notes for Builder

Work in this order:

1. Inspect `web/templates/module_toolkit.html` around `loadToolkitHomebrewReview`, `renderToolkitHomebrewFidelityReview`, and the upload polling handler.
2. Add the required-mode parameter to `loadToolkitHomebrewReview`.
3. Update all required workflow calls to pass required mode where appropriate.
4. Add the review action fallback helper.
5. Ensure no duplicate buttons appear when the normal fidelity panel already renders actions.
6. Update status copy.
7. Add or extend tests.

Likely test file:

- `scripts/test_toolkit_module_build_publication_parity.py` for source-contract checks against template JavaScript.

Possible new test file if more precise:

- `scripts/test_toolkit_fidelity_review_ui_deadlock.py`

Suggested tests can be string/source-contract based because this UI is inline template JavaScript.

## Test Strategy

Add source-contract tests that assert:

1. `loadToolkitHomebrewReview` supports required/force-visible mode.
2. The advanced-mode early return does not apply when required mode is true.
3. The `awaiting_review` polling branch calls review loading with required mode.
4. A fallback review action helper exists and is called after fidelity review rendering.
5. Disabled approve reason helper exists and reads refusal/status/blocker/blueprint reasons.
6. The misleading `Legacy Homebrew job is awaiting review` string is removed or no longer used for accurate-ingest states.
7. Backend strict approval code remains present: `fidelity_review_not_approvable` still exists in `toolkit_homebrew_routes.py`.

Manual smoke after implementation:

1. Start the toolkit.
2. Trigger an accurate-ingest upload that reaches `awaiting_review`.
3. Confirm review controls show without `?homebrewAdvanced=1`.
4. Confirm approvable review can be approved.
5. Confirm approved accurate-ingest review shows `Start Build`.
6. Confirm blocked/unready review shows disabled approve reason and enabled reject/refresh.
