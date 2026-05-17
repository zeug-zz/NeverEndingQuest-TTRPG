# Builder Prompts: toolkit-accurate-ingest-review-ui-fidelity-panel

Use these prompts sequentially. Each step MUST stop after verification and report evidence before the next step starts.

---

## Step 1 Builder Prompt (full variant)

Implement OpenSpec `toolkit-accurate-ingest-review-ui-fidelity-panel` Step 1 only.

Goal: Add an artifact-only fidelity review helper for accurate-ingest workspace review payloads.

Allowed files: `web/extensions/toolkit_homebrew_fidelity_review.py` (new), `utils/toolkit_homebrew_upload_contract.py` only if narrow load helpers are needed, and a new focused test file under `scripts/`.

Forbidden changes: Do not touch routes, templates, `ModuleBuilder`, packet builder execution, build-time gates, or narrative enrichment.

Required contract:
- Add SPDX/header and ASCII-only user-facing text.
- Implement `is_accurate_ingest_workspace(workspace)`, `build_fidelity_review_payload(workspace)`, and `can_approve_fidelity_review(payload)`.
- Payload MUST summarize fidelity status, blockers, warnings, coverage counts, repair attempts, blueprint status, artifact paths, and legacy mode.
- Accurate-ingest missing/malformed required artifacts MUST fail closed with `can_approve: false`.
- Legacy workspaces MUST return mode `legacy` without blocking.

Edit Strategy: Apply one anchored patch at a time, then run py_compile before the next patch.

Verify:
- `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_fidelity_review.py`
- Add/run helper tests for clean, repaired, blocked, missing artifact, malformed artifact, and legacy payloads.

Report: changed files, test command output, and one example payload for blocked fidelity.

---

## Step 2 Builder Prompt (full variant)

Implement OpenSpec `toolkit-accurate-ingest-review-ui-fidelity-panel` Step 2 only.

Goal: Integrate fidelity review payload into Homebrew upload routes and pause accurate-ingest jobs before build.

Allowed files: `web/routes/toolkit_homebrew_routes.py`, `model_config.py`, existing route test file(s), and `web/extensions/toolkit_homebrew_fidelity_review.py` only for helper refinements discovered during route integration.

Forbidden changes: Do not edit templates yet. Do not start build-time fidelity gates. Do not change `ModuleBuilder` internals. Do not alter legacy auto-build behavior except behind accurate-ingest review classification.

Required contract:
- Add `ENABLE_ACCURATE_INGEST_FIDELITY_REVIEW_PANEL = True` default flag.
- After normalization success, if review enabled and workspace is accurate-ingest, job MUST pause at a reviewable state and MUST NOT auto-start build.
- Legacy workspaces or disabled flag MUST keep existing auto-approve/build behavior.
- `GET /api/toolkit/homebrew/jobs/<job_id>/review` MUST include `fidelity_review` when available.
- Review approval POST MUST reject approval if `can_approve_fidelity_review(...)` is false.
- Build start POST MUST re-check fidelity eligibility before invoking packet builder.

Edit Strategy: Apply one anchored patch at a time; run py_compile after route edits before tests.

Verify:
- `.venv/bin/python -m py_compile web/routes/toolkit_homebrew_routes.py model_config.py`
- Route tests for accurate-ingest pause, blocker approval rejection, blocker build-start rejection, and legacy auto-build compatibility.

Report: state transitions before/after, routes touched, tests run.

---

## Step 3 Builder Prompt (full variant)

Implement OpenSpec `toolkit-accurate-ingest-review-ui-fidelity-panel` Step 3 only.

Goal: Render source fidelity review state in the Homebrew toolkit UI.

Allowed files: `web/templates/module_toolkit.html` and focused template/source-contract tests.

Forbidden changes: Do not modify backend route behavior in this step. Do not add build-time gates or narrative enrichment. Do not redesign unrelated toolkit UI.

Required contract:
- Render a fidelity review panel when review payload contains accurate-ingest fidelity state.
- Show status badge, blocker count, warning count, repair attempt count, blueprint readiness, and artifact path hints.
- Show coverage counts for NPCs, locations, plot, puzzles, clues, encounters, items, and tone when present.
- Disable/hide approve/build actions when `fidelity_review.can_approve` is false and display refusal reason.
- Legacy reviews without `fidelity_review` MUST render existing controls as before.

Verify:
- Run existing template/source-contract tests or add focused tests if no direct runner exists.
- If extracting inline JS is required, run `node --check` on the extracted script or existing JS validation pattern used by the repo.

Report: UI surfaces added, selectors/functions touched, verification output.

---

## Step 4 Builder Prompt (full variant)

Implement OpenSpec `toolkit-accurate-ingest-review-ui-fidelity-panel` Step 4-5 verification only.

Goal: Complete regression coverage and prove phase-boundary constraints.

Allowed files: tests only, unless a small bug fix is required by failing tests.

Forbidden changes: No new features beyond the existing specs.

Required contract:
- Helper tests cover clean, repaired, degraded-without-blockers, blocked, failed, missing-artifact, malformed-artifact, and legacy workspace payloads.
- Route tests prove accurate-ingest pauses at review, blockers cannot approve/build, and legacy auto-build remains.
- Template/source-contract tests prove panel rendering and disabled approve state.
- Source-contract tests prove this change does NOT create `build_fidelity_report.json`, does NOT alter `ModuleBuilder`, and does NOT add narrative enrichment.

Verify:
- `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_fidelity_review.py web/routes/toolkit_homebrew_routes.py model_config.py`
- Run all new tests.
- Run impacted existing tests listed in `tasks.md`.
- `openspec validate toolkit-accurate-ingest-review-ui-fidelity-panel`.

Report: full verification matrix and readiness recommendation.
