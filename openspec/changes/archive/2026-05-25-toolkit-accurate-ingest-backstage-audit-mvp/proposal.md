# Change: Accurate-Ingest Backstage Audit MVP

## Why

The accurate-ingest recovery chain now has deterministic source-fidelity evidence and an archived source-enhanced ModuleBuilder handoff. The next useful step is not another repair pass; it is a read-only backstage auditor that can collect the existing evidence, identify report disagreements, summarize blockers, and recommend the next action without mutating module artifacts.

Numillian currently exposes the exact workflow need: source-fidelity reports can pass while stale or broader toolkit/publishability reports still show failures. Developers need one compact, evidence-backed report that explains which artifact says what, which blockers are real, which are stale/report-consistency debt, and which deterministic command should be run next.

## What Changes

- Add a narrow read-only accurate-ingest audit MVP for one module at a time.
- Collect existing module/report artifacts and optional read-only JSON command output.
- Emit structured audit artifacts under a runtime-only agent run directory.
- Group findings by source-fidelity, build-fidelity, validation, readiness, semantic publishability, and report-consistency domains.
- Recommend the next step without applying fixes, writing waivers, weakening gates, calling ModuleBuilder, or invoking seed writer materialization.

## Impact

- Developers get a compact diagnosis layer for accurate-ingest report state.
- The first backstage assistant proves the evidence/report pattern before a shared harness is extracted.
- Accurate-ingest gates remain authoritative; the auditor summarizes them rather than replacing them.
- Module artifacts remain untouched unless a later explicitly approved change performs repair.

## Non-Goals

- Do not mutate module JSON, source artifacts, benchmark fixtures, reports, or publication files.
- Do not create source-fidelity waivers.
- Do not refresh module-level reports in place.
- Do not call ModuleBuilder, seed writer, media generator, or finisher routes.
- Do not introduce a broad `core/agents/backstage/` harness in this first slice.
- Do not use live provider/LLM calls for MVP pass/fail decisions.

## MUST Constraints

- The auditor SHALL be read-only for module artifacts and source artifacts.
- The auditor SHALL consume existing deterministic report artifacts first.
- The auditor MAY run existing benchmark/publishability commands in JSON mode, but SHALL NOT write their output back into the module directory.
- The auditor SHALL emit evidence references with paths, hashes, compact status summaries, and timestamps.
- The auditor SHALL group findings by deterministic domains and include report-disagreement findings.
- The auditor SHALL NOT create waivers, weaken gates, call ModuleBuilder, call seed writer, or enter the live generation loop.
- Tests SHALL prove the auditor does not mutate module artifacts.

## SHOULD Guidance

- Prefer a small script/helper pair over a generic backstage framework in this MVP.
- Prefer deterministic JSON parsing and command summaries over prose-only diagnosis.
- Prefer fixture tests with temp module directories for mutation-safety checks.
- Keep output compact enough for developer review.
- Use Numillian report disagreement as an example condition, not as something to repair in this change.

## Rollback

This change is additive and read-only. Rollback is removal of the new script/helper/tests and OpenSpec artifacts. No module state rollback should be required.

## Dependencies

- `toolkit-accurate-ingest-numillian-npc-location-preservation` is archived and restored source fidelity to pass.
- `toolkit-accurate-ingest-modulebuilder-handoff` is archived and restored source-enhanced ModuleBuilder handoff as the default GUI route.
- `plans/backstage-agents.md` identifies this read-only auditor as the recommended first backstage slice.
