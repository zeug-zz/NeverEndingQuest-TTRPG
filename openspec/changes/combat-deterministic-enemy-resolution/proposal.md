# Proposal

## Why

The accepted G5 verdict is FAIL because enemy `/end` batches exceed the fixed provider-call, work-only latency, and file-write targets. This follow-on transfers those targets unchanged and replaces supported enemy attack mechanics plus mandatory LLM validation with a Python-owned resolution ledger and one narration-only call, while keeping unsupported batches on the existing generate-and-validate path.

## What Changes

- Add a seeded, deterministic enemy attack resolver that plans the entire batch into an immutable ledger before any state mutation. Add optional, schema-validated `multiattack` action/count declarations on monsters and an explicit optional leader marker on encounter combatants; an undeclared bare Multiattack remains unsupported.
- Resolve supported single-target weapon attacks and interim morale boundaries from current combat state. Bloodied-only enemies remain supported and carry a ledger flag; near-death enemies (positive HP at or below 25% max HP), a downed designated leader, or multiple leaders route the entire batch through the existing LLM generation and validation path. Intelligent self-preservation belongs to the follow-on `combat-tactical-brain` change.
- For supported batches, make exactly one router narration call, verify narration against the ledger, and use deterministic ledger-derived narration with a recorded reason if output checks fail. Do not issue a second narration or validator call for such a failure.
- Persist each supported batch's assembled user input and final narration once as a pre-apply atomic history checkpoint, then persist changed PC files once each and the final encounter once; preserve character-before-encounter order. Trace the resolver/fallback decision and provide a rollback feature flag. Do not implement turn receipts, applied IDs, commit-before-publication reordering, or general code-owned round advancement; D12 permits only the two scoped lifecycle transitions for supported batches. `combat-turn-commit-and-receipts` owns code-owned round advancement for all paths.
- Extend the existing capture, trace, and report surfaces with a G5R gate. Preserve the existing G5 thresholds, compare three runs per party shape by medians, define outcome-normalized no-regression accounting before live capture, and retain raw metrics alongside normalized metrics.
- Keep all existing static combat prompt files byte-identical. `ENABLE_CHAT_STREAMING` remains out of scope.

## Capabilities

### New Capabilities

- `combat-deterministic-enemy-resolution`: Defines the supported enemy mechanics, immutable ledger, multiattack data contract, and whole-batch fallback boundary.
- `combat-enemy-batch-execution`: Defines narration-only handling, narration checks and template fallback, atomic batch application, tracing, and rollback behavior.
- `combat-enemy-resolution-g5r`: Defines the repeated live acceptance gate for the transferred G5 targets and regression comparisons.

### Modified Capabilities

- `combat-decision-trace-events`: Add bounded enemy-resolver and whole-batch fallback decision outcomes and reasons.
- `combat-turn-trace-schema`: Add bounded batch correlation and resolution/write observations needed by G5R.
- `combat-latency-report-script`: Add G5R median and outcome-normalized comparison reporting while preserving raw metrics and existing report behavior.
- `combat-latency-smoke-fixtures`: Reuse the existing P1/P4 capture scenarios for repeated G5R runs without changing their action scripts.

## Impact

Runtime touchpoints include the `core/combat/` turn, combat-manager, narration, persistence, and decision seams; `schemas/mon_schema.json`, `schemas/encounter_schema.json`, and their validators; `model_config.py`; and provider-free combat tests. Tooling touchpoints are the existing Capture_Arena seeder, capture driver/evidence validator, latency trace/report, and capture skill. Shared combat behavior must preserve 1-PC-party and multi-PC-party compatibility, phase/initiative/death-save/resume-replay contracts, and Python authority over mechanics. Narration uses the existing `llm.call` router path; its timeout, retry, outage, quota, and terminal-error behavior remain router-owned. No static combat prompt is changed.
