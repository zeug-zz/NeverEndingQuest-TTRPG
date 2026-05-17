# Executor Prompts: Narrative Enrichment Placeholder

## Step 1: Helper Artifact Model

Implement OpenSpec `toolkit-accurate-ingest-narrative-enrichment-placeholder` Step 2 only.

Goal: Add an artifact-only helper for future narrative enrichment planning.

Allowed files:
- `utils/toolkit_narrative_enrichment_plan.py`
- future tests named in `tasks.md`

Forbidden:
- Do not mutate module files.
- Do not call LLM providers.
- Do not apply enrichment patches.
- Do not edit `ModuleBuilder` or `ModuleGenerator`.
- Do not duplicate, bypass, or replace existing `MODULE_SUMMARY.md` generation in the toolkit finisher.

Required:
- Default profile SHALL be `none`.
- Helper SHALL produce `can_apply: false` and `auto_apply: false` in this first implementation.
- Helper SHALL block non-`none` profiles when source/build fidelity contains blockers.
- Helper SHALL include source-lock fields for NPCs, locations, plot topology, puzzle rules, and evidence.

Verify:
- `.venv/bin/python -m py_compile utils/toolkit_narrative_enrichment_plan.py`
- Run new focused tests.

Report: files changed, tests run, and any unresolved design questions.

## Step 2: Artifact Persistence and Report Integration

Implement OpenSpec `toolkit-accurate-ingest-narrative-enrichment-placeholder` Step 3 only.

Goal: Persist `narrative_enrichment_plan.json` as a reviewable artifact after successful source/build fidelity gates.

Allowed files:
- `utils/toolkit_homebrew_upload_contract.py`
- `web/extensions/toolkit_homebrew_packet_builder.py` or the current accurate-ingest report integration point
- focused tests

Forbidden:
- Do not apply enrichment to modules.
- Do not change source-fidelity scoring.
- Do not block accurate ingest when profile is `none`.
- Do not move or regenerate `MODULE_SUMMARY.md`; leave Homebrewery adventure markdown generation in the existing finisher path.

Required:
- Plan generation SHALL occur only after build/source fidelity has no blockers.
- Legacy workspaces SHALL skip the artifact without behavior change.
- Malformed fidelity artifacts SHALL fail closed if a non-`none` enrichment profile is requested.

Verify:
- `.venv/bin/python -m py_compile` for touched Python files.
- Existing build fidelity tests plus new plan persistence tests.

## Step 3: Status Surfacing

Implement OpenSpec `toolkit-accurate-ingest-narrative-enrichment-placeholder` Step 4 only.

Goal: Surface compact plan status without adding auto-apply UI.

Allowed files:
- `web/routes/toolkit_homebrew_routes.py`
- `web/templates/module_toolkit.html`
- focused tests

Forbidden:
- No enrichment text generation.
- No patch/apply button.
- No source-fidelity gate weakening.

Required:
- UI/status SHALL show profile and status (`none`, `skipped`, `planned`, `blocked`).
- Source-fidelity blockers SHALL remain more prominent than enrichment status.
- Legacy/non-accurate-ingest jobs SHALL remain unchanged.

Verify:
- Route/template source-contract tests.
- Existing accurate-ingest review/build status tests.

## Step 4: Verification and Archive Readiness

Implement only final verification for the change.

Required:
- Run all focused tests from tasks.
- Run `openspec validate toolkit-accurate-ingest-narrative-enrichment-placeholder`.
- Confirm no module JSON files were modified.
- Confirm no provider calls are required.

Report:
- PASS/FAIL for each verification command.
- Any residual risks.
