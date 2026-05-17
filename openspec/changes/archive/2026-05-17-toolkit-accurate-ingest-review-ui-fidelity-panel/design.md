## Context

Current upload flow in `web/routes/toolkit_homebrew_routes.py` auto-creates an approved review snapshot after normalization and starts build automatically. Existing review endpoints already exist (`GET/POST /api/toolkit/homebrew/jobs/<job_id>/review`) but accurate-ingest does not yet populate them with source fidelity evidence or require review before build.

## Contract Layer (MUST)

- Accurate-ingest workspaces MUST be identified by existing source-fidelity artifacts, not by module name or UI-only state.
- Accurate-ingest jobs MUST pause after successful normalization when fidelity review is enabled.
- The review payload MUST include compact status from `normalization_fidelity_report.json`, `normalization_report.json`, repair attempts, and `builder_blueprint_report.json` when present.
- The review payload MUST distinguish blockers from warnings/degraded findings.
- Approval/build start MUST fail closed while blocker findings remain.
- Legacy workspaces without accurate-ingest artifacts MUST preserve current behavior.
- Feature-flag-disabled fidelity review MUST preserve current behavior.
- UI rendering MUST be additive and must not remove existing Homebrew upload status/readiness UX.
- Tests MUST prove no real builder/provider calls are made by review-only code paths.
- Python user-facing console/log text introduced by this change MUST be ASCII-only.

## Guidance Layer (SHOULD)

- Add `web/extensions/toolkit_homebrew_fidelity_review.py` as the main review-summary helper to keep route edits thin.
- Keep route state names explicit: `awaiting_review` for reviewable clean/degraded jobs, `fidelity_blocked` or `awaiting_review` with `can_approve=false` for blocker states. Prefer reusing `awaiting_review` if UI compatibility is simpler.
- Store `fidelity_review` compactly in job `result` and regenerate from artifacts in `GET review` so stale job memory does not become authoritative.
- Present repair attempts as a compact latest-first list rather than dumping full repair JSON into the UI.
- Use small template helpers in `module_toolkit.html`; avoid large UI rewrites.

## Architecture

### Backend helper

Create a helper module that performs artifact-only reads:

```python
def build_fidelity_review_payload(workspace: Path) -> Dict[str, Any]:
    """Return compact source-fidelity review state for one workspace."""

def is_accurate_ingest_workspace(workspace: Path) -> bool:
    """Return true when source/fidelity artifacts prove accurate-ingest mode."""

def can_approve_fidelity_review(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Return approval eligibility and refusal reason."""
```

The payload should include:

- `mode`: `accurate_ingest` or `legacy`
- `status`: `clean`, `repaired`, `degraded`, `blocked`, `failed`, `missing`, or `legacy`
- `can_approve`: boolean
- `blockers`: compact finding list
- `warnings`: compact finding list
- `coverage`: counts by category where available
- `repair`: attempt count, latest status, artifact paths
- `blueprint`: blueprint status, fidelity precheck status, artifact paths
- `artifacts`: paths/existence for detailed JSON reports

### Route changes

After normalization succeeds:

- If review panel disabled or workspace is legacy: preserve existing auto-approve/build behavior.
- If accurate-ingest review enabled and payload has blockers: set job state to a reviewable blocked state; do not create an approved snapshot; do not start build.
- If accurate-ingest review enabled and payload has no blockers: set job state to `awaiting_review`; do not auto-start build.

In `GET /review`, include `fidelity_review` and build eligibility fields.

In `POST /review`, reject approval when `can_approve_fidelity_review(...)` is false. Reject state changes if artifacts changed between GET and POST and blocker state changed.

In `POST /build`, re-check fidelity approval eligibility for accurate-ingest workspaces before build start.

### Frontend changes

In `web/templates/module_toolkit.html`, render a fidelity panel in the Homebrew upload review/status section:

- status badge
- blocker count and compact blocker table
- warning/degraded findings
- required NPC/location/plot/puzzle/clue coverage counts
- latest repair attempt summary
- blueprint readiness summary
- action guidance: approve, abort/reject, or repair already attempted/exhausted

### Error handling

- Missing detailed artifacts in an accurate-ingest workspace should produce status `missing` and block approval.
- Malformed JSON should produce status `failed` and block approval.
- Legacy workspaces should not be blocked by missing accurate-ingest artifacts.

## Phase Boundaries

This phase is pre-build review gating only. It must not perform post-build audits, modify generated modules, or enrich narrative fields.
