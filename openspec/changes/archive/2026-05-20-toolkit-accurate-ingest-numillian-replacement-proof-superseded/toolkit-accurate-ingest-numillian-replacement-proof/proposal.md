# Proposal: Accurate-Ingest Numillian Replacement Proof

## Problem

The accurate-ingest GUI builder path has been stabilized in earlier slices, but the production proof is not complete until `modules/The_Hidden_City_of_Numillian/` is verified as a source-faithful replacement generated from the original uploaded markdown, not restored from the old inaccurate ingest.

The plan in `plans/accurate-ingest-fix.md` identifies Numillian as the primary source case. It requires the production module to preserve source locations, NPCs, puzzles, lore, tone, and publication-gate evidence before manual UI bug testing resumes.

Without this proof, the project can have a working pipeline in tests while the main tester-facing Numillian module remains partial, stale, or accidentally derived from the legacy v1 output.

## Objective

Prove the current production Numillian module is built or refreshed from source truth and passes the validation, source-fidelity benchmark, and publishability gates required for tester-facing publication.

Source truth:

```text
Local_Docs/modules/hombrew/modules/The Hidden City of Numillian.md
```

Production target:

```text
modules/The_Hidden_City_of_Numillian/
```

Legacy comparison/archive target:

```text
modules/The_Hidden_City_of_Numillian_v1/
```

## Proposed Solution

Create a focused proof slice that validates the production Numillian replacement end to end:

1. Confirm the source markdown and v1 archive roles.
2. Build or refresh the production module through deterministic accurate-ingest artifacts.
3. Verify canonical module artifacts, seed artifacts, reports, and publication contract boundaries.
4. Run module validation, source-fidelity benchmark, and publishability audit.
5. Confirm `MODULE_SUMMARY.md` is final-derived presentation output, not source-fidelity authority.
6. Confirm old v1 remains non-production unless explicitly listed as an archive/comparison artifact.

This slice should implement proof and remediation only for Numillian. It must not weaken pipeline gates or restore the old inaccurate ingest as production.

## Non-Goals

- This change does not make `modules/The_Hidden_City_of_Numillian_v1/` the production module.
- This change does not bypass readiness, semantic, media, benchmark, or source-fidelity gates.
- This change does not treat `MODULE_SUMMARY.md` as source truth.
- This change does not broaden accurate-ingest behavior for all modules beyond proof fixes required by Numillian.
- This change does not auto-publish to Git or push to origin.

## Contract Layer (MUST)

- Production Numillian MUST be derived from the original source markdown or its deterministic accurate-ingest artifacts.
- Production Numillian MUST preserve all 13 benchmark source locations by original source name or approved mapping.
- Production Numillian MUST preserve required benchmark NPC threshold and required fixture expectations.
- Trial-at-the-Door, skull riddle, flooding room puzzle, kill-the-dog mindscape, Gatepact lore, Kobe protection objective, and quirky source tone MUST remain present in canonical module artifacts.
- Final validation, benchmark, source-fidelity, and publishability reports MUST agree on whether the module is publishable.
- `MODULE_SUMMARY.md` MUST be generated from final audited module content and MUST NOT improve or repair source-fidelity scoring.
- The old v1 module MUST remain separate and MUST NOT be accidentally selected as production unless explicitly registered as archive/comparison content.

## Guidance Layer (SHOULD)

- Prefer deterministic rebuild or refresh commands over manual JSON editing.
- If remediation is needed, make schema-valid targeted fixes and rerun reports from current artifacts.
- Keep runtime files ignored and canonical files trackable without `git add -f`.
- Preserve workspace/report evidence when practical for auditability.
- Treat media debt as explicit handoff debt, not silent publishability success.

## Risks

| Risk | Mitigation |
|---|---|
| Rebuild overwrites source-faithful content with legacy concept output | Require source markdown and accurate-ingest artifacts as proof inputs. |
| v1 archive is confused with production module | Add explicit guard/audit behavior and status checks. |
| `MODULE_SUMMARY.md` masks missing canonical data | Verify summary is final-derived and not a source-fidelity input. |
| Publishability passes despite blocked source fidelity | Require publishability/source-fidelity agreement. |
| Runtime files enter the staged canonical artifact set | Verify gitignore/publication contract boundaries. |

## Success Criteria

1. Numillian validation passes or reports only accepted explicit media-handoff debt.
2. Benchmark status is pass or accepted degraded-with-waiver with documented limitations.
3. Publishability status is pass only when source fidelity allows publication.
4. Required Numillian fixture expectations are present in canonical artifacts.
5. `MODULE_SUMMARY.md` reflects final audited content and is not a source-fidelity repair path.
6. v1 remains non-production and cannot be accidentally selected by normal module selection/publication flows.
7. Git status for Numillian is explainable as intentional canonical replacement, not partial failed rebuild.
