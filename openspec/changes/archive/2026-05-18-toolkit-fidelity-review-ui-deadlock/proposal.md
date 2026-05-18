# Proposal: Toolkit Fidelity Review UI Deadlock Fix

## Problem

Accurate-ingest uploads can reach `awaiting_review` after normalization, repair attempts, and blueprint generation complete. The server logs `paused for fidelity review`, but the toolkit UI can leave the operator with only raw JSON output and no visible approval controls.

Observed failure mode:

1. Homebrew upload reaches `job.status == "awaiting_review"`.
2. Polling renders a warning plus raw JSON status output.
3. Polling stops.
4. `loadToolkitHomebrewReview(...)` may not render the actionable review panel, especially when `HOME_BREW_ADVANCED_MODE` is disabled.
5. The build remains paused with no visible way for the operator to approve, reject, refresh, or continue.

This is a UI deadlock. The fidelity gate itself is correct in principle, but required approval UI is incorrectly treated like an advanced/optional panel.

## Proposed Solution

Make the fidelity review gate actionable whenever a job is waiting for review.

1. Required review UI MUST load even when `HOME_BREW_ADVANCED_MODE` is disabled.
2. `awaiting_review` status MUST show an explicit action row with review controls.
3. The UI MUST clearly distinguish approvable, blocked, and stale/missing review states.
4. Approval MUST remain strict: the backend SHALL NOT allow broad force approval over blockers, failed fidelity status, missing artifacts, or an unready blueprint.
5. If approval is disabled, the UI MUST explain why and still provide `Reject Review` and `Refresh Review` controls.
6. The misleading `Legacy Homebrew job is awaiting review` copy SHOULD be changed to accurate wording for both legacy and accurate-ingest review states.

## Non-Goals

- Do not weaken `can_approve_fidelity_review(...)` for blockers, failed status, missing artifacts, or unready blueprint reports.
- Do not add a broad `force: true` backend bypass.
- Do not redesign the whole Module Toolkit UI.
- Do not change the accurate-ingest normalizer, repair loop, blueprint generation, or source-fidelity scoring behavior.
- Do not make the build auto-start after accurate-ingest approval; the existing explicit `Start Build` step remains valid.
- Do not require LLM calls or provider changes.

## Success Criteria

1. A job in `awaiting_review` always displays actionable review controls in the GUI.
2. Required review controls render even when homebrew advanced mode is off.
3. An approvable accurate-ingest review shows an enabled `Approve Fidelity Review` button.
4. A non-approvable accurate-ingest review shows a disabled approve state with a clear refusal reason, plus enabled `Reject Review` and `Refresh Review` buttons.
5. The backend continues to reject non-approvable approval attempts with the current `fidelity_review_not_approvable` semantics.
6. Existing legacy review and overwrite-confirmation behavior remains compatible.
7. Regression tests cover the deadlock: advanced mode off + `awaiting_review` still renders review controls.

## Architecture Impact

- **Frontend-only primary fix**: The main change is in `web/templates/module_toolkit.html` review loading/rendering.
- **Backend remains authoritative**: Existing review endpoint and approval validation stay strict.
- **Additive UX fallback**: Adds required-action rendering for `awaiting_review`; no module data mutation.
- **Merge-safe**: Keep changes local to the toolkit route/template surface, using existing endpoint contracts.
