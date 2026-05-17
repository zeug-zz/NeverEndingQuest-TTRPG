# Tasks: Toolkit Accurate-Ingest Narrative Enrichment Placeholder

## 1. Planning Artifact Review

- [x] 1.1 Review proposal, design, and specs for source-lock correctness.
- [x] 1.2 Confirm non-goals: no auto-apply, no provider calls, no module mutation.
- [x] 1.3 Confirm whether profile selection is user-facing or config-only for first implementation.
- [x] 1.4 Confirm existing `MODULE_SUMMARY.md` generation remains owned by the toolkit finisher and is not duplicated by this change.

## 2. Future Helper Artifact Model

- [x] 2.1 Add `utils/toolkit_narrative_enrichment_plan.py` with artifact-only helpers.
- [x] 2.2 Define a deterministic plan shape with profile, status, source locks, eligible fields, field budgets, blockers, warnings, and artifact refs.
- [x] 2.3 Default profile selection to `none`.
- [x] 2.4 Reject or block plans when build/source fidelity has blockers.

## 3. Contract Integration

- [x] 3.1 Add workspace path and persistence/load helpers for `narrative_enrichment_plan.json`.
- [x] 3.2 Integrate plan generation after source/build fidelity gates pass or degrade without blockers.
- [x] 3.3 Ensure accurate ingest can complete without enrichment.
- [x] 3.4 Ensure generated plans cannot mutate module files.

## 4. Status Surfacing

- [x] 4.1 Add compact status payload fields for enrichment profile and plan status.
- [x] 4.2 Surface `none`, `skipped`, `planned`, and `blocked` states without hiding source-fidelity blockers.
- [x] 4.3 Preserve legacy/non-accurate-ingest behavior.

## 5. Tests

- [x] 5.1 Add contract tests for default `none` profile.
- [x] 5.2 Add tests proving blocked source/build fidelity prevents non-`none` enrichment planning.
- [x] 5.3 Add tests proving plans are artifact-only and do not mutate modules.
- [x] 5.4 Add tests for profile vocabulary and field-budget serialization.
- [x] 5.5 Add source-lock tests proving required NPCs, locations, plot topology, puzzle rules, and evidence cannot be overwritten by enrichment planning.

## 6. Verification

- [x] 6.1 Run `.venv/bin/python -m py_compile` for any modified Python files.
- [x] 6.2 Run new narrative enrichment plan contract tests.
- [x] 6.3 Run existing accurate-ingest fidelity gate tests impacted by report integration.
- [x] 6.4 Run `openspec validate toolkit-accurate-ingest-narrative-enrichment-placeholder`.

## Guidance

Implementation should not begin until this scaffold is reviewed. Keep all tasks unchecked until the apply step starts.
