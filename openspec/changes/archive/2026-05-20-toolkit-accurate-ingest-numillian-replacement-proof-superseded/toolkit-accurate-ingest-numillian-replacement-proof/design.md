# Design: Accurate-Ingest Numillian Replacement Proof

## Overview

This change is a proof-and-remediation slice for one module: `The_Hidden_City_of_Numillian`.

It closes the accurate-ingest stabilization plan by proving that the production module is source-faithful, gate-checked, and publishable under the same contracts future GUI uploads must satisfy.

The proof chain is:

```text
source markdown
  -> deterministic accurate-ingest artifacts
  -> production module canonical files
  -> validation report
  -> source-fidelity benchmark/report
  -> publishability audit
  -> final-derived MODULE_SUMMARY.md
```

## Decision 1: Source Markdown Is Authority

The only production source authority for this proof is:

```text
Local_Docs/modules/hombrew/modules/The Hidden City of Numillian.md
```

The legacy module at `modules/The_Hidden_City_of_Numillian_v1/` may be used for comparison only. It must not be copied into production as the primary fix.

## Decision 2: Production Module Artifact Set

The production module must contain canonical publication artifacts, including:

```text
module_context.json
module_context_BU.json
module_plot_BU.json
party_tracker_BU.json
areas/*_BU.json
map_*.json
npcs_seed.json
monsters_seed.json
seed_source_report.json
source_fidelity_report.json
validation_report.json
toolkit_build_report.json
accurate_ingest_benchmark_report.json
MODULE_SUMMARY.md
README.md
PLAYER_GUIDE.md (if generated)
```

Runtime files remain ignored and should not be committed:

```text
module_plot.json
party_tracker.json
areas/*.json except *_BU.json
player_quests_*.json
encounters/**
```

## Decision 3: Benchmark Expectations Are Publication Evidence

The Numillian fixture in `data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json` defines required proof expectations. The final benchmark must preserve:

- all 13 source locations by original source name or approved mapping,
- required NPC threshold,
- Trial-at-the-Door,
- skull riddle,
- flooding room puzzle,
- kill-the-dog mindscape,
- Gatepact lore,
- Kobe protection objective,
- quirky source tone.

Any degraded benchmark status must be explicitly justified and waived through the existing source-fidelity waiver contract before publication can pass.

## Decision 4: Publishability Is Composed, Not Assumed

Publishability must be determined by the existing audit composition:

```text
ready_status + semantic publishability + source_fidelity_status
```

A passing readiness report alone is insufficient. A blocked source-fidelity report must block publishability.

## Decision 5: MODULE_SUMMARY Is Presentation Output

`MODULE_SUMMARY.md` is generated after module materialization and finishing. It may help humans review the module, but it cannot be used to repair or improve source-fidelity scoring.

The proof must confirm summary content reflects final audited module artifacts and does not contain stale v1 or generic replacement plot content.

## Decision 6: v1 Archive Guard

The old inaccurate module may remain for historical comparison, but normal module selection/publication surfaces must not accidentally treat it as the current production module.

Accepted v1 states:

- absent,
- present but unregistered/non-production,
- explicitly documented as archive/comparison only.

Rejected v1 states:

- registered as a normal published module under the current production identity,
- selected by default module discovery in place of production,
- used as the source of production canonical artifacts.

## Likely Touchpoints

- `scripts/test_accurate_ingest_numillian_end_to_end.py` for GUI-equivalent proof coverage.
- `scripts/benchmark_accurate_ingest.py` for benchmark execution.
- `scripts/audit_module_publishability.py` for final gate verification.
- `core/validation/validate_module_files.py` for schema/reference validation.
- `modules/The_Hidden_City_of_Numillian/` for canonical production artifacts if remediation is needed.
- `modules/published_modules.json` only if registration remediation is needed.
- `README.md` only if publication listing remediation is needed.

## Rollback

If deterministic Numillian production proof fails and cannot be repaired in this slice, leave the production module unpublished/not-publishable and document blockers. Do not restore v1 as production without an explicit future change.
