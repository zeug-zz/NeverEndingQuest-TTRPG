## 1. Fidelity Review Helper

- [x] 1.1 Add `web/extensions/toolkit_homebrew_fidelity_review.py` with SPDX/header and artifact-only review helpers.
- [x] 1.2 Implement `is_accurate_ingest_workspace(workspace)` using source/fidelity/blueprint artifact existence, not module names.
- [x] 1.3 Implement `build_fidelity_review_payload(workspace)` that reads normalization fidelity, normalization report rollup, repair attempts index, and builder blueprint report.
- [x] 1.4 Implement compact blocker/warning/coverage extraction with bounded finding lists and artifact paths.
- [x] 1.5 Implement `can_approve_fidelity_review(payload)` with fail-closed outcomes for blockers, failed fidelity, malformed/missing accurate-ingest artifacts, or non-ready blueprint where required.

## 2. Route Integration

- [x] 2.1 Add a feature flag such as `ENABLE_ACCURATE_INGEST_FIDELITY_REVIEW_PANEL` in `model_config.py` defaulting to enabled.
- [x] 2.2 Update `web/routes/toolkit_homebrew_routes.py` normalization success flow so accurate-ingest jobs pause for review instead of auto-starting build.
- [x] 2.3 Preserve existing auto-approve/build behavior for legacy workspaces or disabled review flag.
- [x] 2.4 Add `fidelity_review` to `GET /api/toolkit/homebrew/jobs/<job_id>/review` responses.
- [x] 2.5 Update review approval POST to reject approval when fidelity review is not approvable.
- [x] 2.6 Update build start POST to re-check fidelity eligibility before build starts.
- [x] 2.7 Ensure blocked review state remains reviewable in the UI and exposes artifact paths/reasons.

## 3. UI Panel

- [x] 3.1 Add a fidelity review panel renderer in `web/templates/module_toolkit.html` using the existing Homebrew upload status/review UI patterns.
- [x] 3.2 Display fidelity status badge, blocker count, warning count, repair attempt count, and blueprint readiness.
- [x] 3.3 Display compact tables/lists for required NPC/location/plot/puzzle/clue coverage where available.
- [x] 3.4 Disable/hide approve/build actions when `fidelity_review.can_approve` is false and show the refusal reason.
- [x] 3.5 Preserve existing legacy review and build UI behavior when no fidelity review payload is present.

## 4. Tests

- [x] 4.1 Add helper tests for clean, repaired, degraded-without-blockers, blocked, failed, missing-artifact, malformed-artifact, and legacy workspace payloads.
- [x] 4.2 Add route tests proving accurate-ingest normalization success pauses at review and does not auto-start build.
- [x] 4.3 Add route tests proving blocker approval and build start fail closed before builder invocation.
- [x] 4.4 Add legacy compatibility tests proving non-accurate-ingest uploads keep current auto-build behavior.
- [x] 4.5 Add template/source-contract tests for fidelity panel rendering, disabled approve state, and no Phase 8/9 scope creep.

## 5. Verification

- [x] 5.1 Run `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_fidelity_review.py web/routes/toolkit_homebrew_routes.py model_config.py`.
- [x] 5.2 Run new fidelity review helper/route/template tests.
- [x] 5.3 Run existing impacted tests: `scripts.test_packet_builder_blueprint_handoff`, `scripts.test_toolkit_homebrew_normalizer`, and `scripts.test_toolkit_module_build_publication_parity` if touched.
- [x] 5.4 Run `openspec validate toolkit-accurate-ingest-review-ui-fidelity-panel`.
- [x] 5.5 Confirm this slice does not create `build_fidelity_report.json`, does not alter `ModuleBuilder`, and does not add narrative enrichment.
