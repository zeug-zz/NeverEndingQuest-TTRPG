## Why

Accurate-ingest Phases 2-4 now produce source-backed artifacts (`source_graph.json`, section extractions, identity/topology reports, `normalization_fidelity_report.json`, repair attempts, `builder_blueprint.json`, and source-locked `builder_narrative.md`). The current readable-source upload route still auto-approves and auto-starts packet build after normalization, so a facilitator cannot review source fidelity before the build starts.

This is unsafe for the Numillian class of failures: even if Python detects missing required NPCs, dropped keyed locations, unsupported replacement plotlines, or blocked fidelity status, the UI does not yet expose those findings as a pre-build review surface.

## What Changes

- Add a fidelity review payload assembled from existing accurate-ingest workspace artifacts.
- Surface source fidelity status, required-atom coverage, blocking findings, warnings, repair attempts, and blueprint readiness in the existing Homebrew upload review flow.
- Pause accurate-ingest jobs at a review state after normalization instead of auto-starting build.
- Prevent approval/build start when fidelity blockers remain.
- Preserve legacy auto-build behavior for non-accurate-ingest workspaces and disabled fidelity-review mode.
- Add source-contract tests proving this slice does not add build-time fidelity gates or narrative enrichment.

## Phase Mapping

This is the next accurate-ingest slice after Phase 4. In the older roadmap text this corresponds to the **Review UI Fidelity Panel** phase. The earlier roadmap's "Normalization Fidelity Verifier and Repair Loop" work has already been completed and archived as Phase 3.

## Capabilities

### New Capabilities

- `toolkit-fidelity-review-payload`: Backend review payload includes source-fidelity and repair-history summaries from workspace artifacts.
- `toolkit-fidelity-approval-gate`: Accurate-ingest review approval/build start fails closed while source-fidelity blockers remain.
- `toolkit-fidelity-review-ui-panel`: Toolkit UI displays fidelity coverage, blockers, warnings, repair history, and build eligibility before approval.

## Non-Goals

- Do not implement build-time fidelity gates (`build_fidelity_report.json` stage gates remain a later phase).
- Do not alter `ModuleBuilder`/`ModuleGenerator` internals.
- Do not add narrative enrichment or enrichment plans.
- Do not introduce destructive packet repair operations.
- Do not require manual review for legacy workspaces that lack accurate-ingest artifacts.
- Do not change module publication/readiness gates except to preserve existing post-build behavior.

## Impact

- **Backend:** `web/routes/toolkit_homebrew_routes.py`, new extension helper under `web/extensions/`, and possibly `utils/toolkit_homebrew_upload_contract.py` load helpers.
- **Frontend:** `web/templates/module_toolkit.html` review/status rendering.
- **Tests:** New or extended route/template/source-contract tests covering review payload, approval gate, and legacy compatibility.
- **Risk:** Existing auto-build flow is sensitive. The implementation must branch only for accurate-ingest workspaces and preserve current behavior elsewhere.

## Rollback

- A feature flag (for example `ENABLE_ACCURATE_INGEST_FIDELITY_REVIEW_PANEL`) SHOULD allow reverting to current auto-build behavior.
- If review payload assembly fails unexpectedly, accurate-ingest jobs SHOULD fail closed with a reviewable error; legacy jobs SHOULD continue through existing behavior.
