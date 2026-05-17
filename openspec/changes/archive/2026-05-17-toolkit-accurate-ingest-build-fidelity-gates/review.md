# Review Packet: toolkit-accurate-ingest-build-fidelity-gates

## Decision Needed

Approve this OpenSpec plan before a builder implements it.

## Scope Summary

This change adds post-build source fidelity gates for accurate-ingest workspaces. It audits generated module output against source/blueprint artifacts, persists `build_fidelity_report.json` and `source_fidelity_report.json`, and blocks finishing/publication when critical source content is lost.

## Why This Is Next

The review UI now blocks unsafe builds before construction. The remaining risk is after construction: a module can be generated but source-divergent. This phase catches that before finishing/publication.

## In Scope

- Artifact-only build fidelity helper.
- Build report persistence.
- Final source fidelity rollup.
- Fail-closed post-build gate for critical source losses.
- Minimal existing-status UI/report surfacing.
- Legacy compatibility.

## Out Of Scope

- Narrative enrichment.
- Waiver policy.
- Automatic repair of generated modules.
- `ModuleBuilder`/`ModuleGenerator` refactor.
- Build-time provider calls.

## Key Review Questions

1. Should advisory tone/profile mismatches be warning-only by default? Proposed answer: yes.
2. Should critical source omissions always block, with no waiver in this phase? Proposed answer: yes.
3. Should this gate run before readiness/finisher? Proposed answer: yes, so source-divergent builds do not enter normal publication checks.
4. Should legacy workspaces skip this gate? Proposed answer: yes.
5. Should generated modules remain unmodified by this gate? Proposed answer: yes.

## Approval Criteria

- The scope matches the intended next phase.
- The non-goals are acceptable.
- Builder prompts are sufficiently constrained to avoid scope creep.
- Verification gate is acceptable for phase completion.

## Recommended Next Action

If approved, run builder Step 1 from `executor_prompts.md`.
