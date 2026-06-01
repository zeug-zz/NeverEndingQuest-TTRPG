# Change: Accurate-Ingest Numillian Release-Proof Finalization

## Why

The accurate-ingest recovery chain has restored the core architecture and the hardest source-fidelity benchmark now passes for `The_Hidden_City_of_Numillian`: NPCs `23/23`, locations `13/13`, puzzles `3/3`, lore `2/2`, and tone preservation pass.

The remaining problem is release proof, not source preservation. Current audit state shows `ready_status=pass`, `source_fidelity_status=pass`, but `publishable_status=fail` and `effective_publishable_status=blocked`. Known blockers include semantic audit phrase debt from `module_plot.json#plotPoints[PP010].title`, absent module-local monster artifacts for visible source monster refs, and stale/failed report agreement in `toolkit_build_report.json`.

This change converts the source-fidelity pass into a publishable, release-ready Numillian module or produces narrow explicit blockers that can be reviewed without weakening any gate.

## What Changes

- Add a diagnostic-first finalization workflow for Numillian release proof.
- Close semantic audit blockers with source-faithful module artifact fixes.
- Finalize source monster references into module-local schema-valid monster artifacts through reuse-first resolution, or preserve explicit unresolved blockers.
- Refresh and align validation, benchmark, source-fidelity, toolkit build, and publishability reports.
- Preserve `MODULE_SUMMARY.md` as a final derived artifact only.

## Non-Goals

- Do not change benchmark thresholds, benchmark fixture data, or benchmark scanner logic.
- Do not weaken validation, readiness, semantic audit, source-fidelity, build-fidelity, or publishability gates.
- Do not create waivers.
- Do not use `MODULE_SUMMARY.md` as source-fidelity repair input.
- Do not invent replacement monsters, NPCs, locations, plotlines, or puzzles to satisfy counts.
- Do not require runtime files for publication.

## MUST Constraints

- Final Numillian release proof SHALL pass validation, source-fidelity benchmark, and publishability audits, or report explicit narrow blockers.
- Current passing source-fidelity categories SHALL remain passing unless a blocker is explicitly documented.
- Semantic audit blockers SHALL be fixed in module artifacts or kept as blockers; audit rules SHALL NOT be weakened.
- Source monster refs SHALL be materialized through reuse-first schema-valid artifacts or recorded as unresolved diagnostics.
- Report artifacts SHALL agree on final status before release readiness is claimed.
- `MODULE_SUMMARY.md` SHALL remain generated from final audited module JSON and SHALL NOT mutate module JSON.

## SHOULD Guidance

- Start diagnostic-only before editing module artifacts.
- Prefer the smallest source-faithful artifact patch for each blocker.
- Reuse existing accurate-ingest monster materialization helpers and report contracts before adding new architecture.
- Keep production Numillian runtime files ignored and out of publication staging.

## Risks

- Fixing semantic blocker phrases may accidentally alter source plot meaning. Mitigation: constrain edits to exact offending generated title/phrase fields and verify source benchmark remains pass.
- Monster finalization may classify NPC-like names incorrectly. Mitigation: require monster/combatant evidence and leave ambiguous refs unresolved.
- Report refresh may mask stale failures. Mitigation: require cross-report agreement and publishability audit pass.

## Rollback

Revert the module artifact/report finalization changes from this change. Existing archived source-enhanced ModuleBuilder handoff, generator source locks, and monster materialization helper work remain additive and can continue to support later finalization attempts.
