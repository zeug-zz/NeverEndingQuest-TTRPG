# Proposal

## Why

The completed synthetic pilot suggests a bounded B-versus-D comparison, but it cannot establish multi-turn continuity, live persisted-state behavior, or player assessment. The owner has now authorized a narrowly bounded research-only Capture Arena extension, so the existing rig can collect auditable evidence without changing production mapping behavior or claiming an improvement over an untested baseline.

## What Changes

- Add one research-only capability for a controlled, four-row Capture Arena comparison of B/P1, D/P1, D/P4, and B/P4, with the approved adjacent-east query and explicit room-display origin (north-up, X east, Y north).
- Extend only the existing Capture Arena seeder, driver, and evaluator, with a narrow sandbox-only bootstrap adapter where required. Compare identical facts under fixed narrator configuration and observed metadata; reset state independently for each row.
- MUST preserve the fixed seven-input route CA01 -> CA02 -> CA03 -> CA02 -> CA01, including Mira dialogue, the P4 active-PC transition from Acheron to Merisiel, and a one-minute wait verified against canonical persisted world time. Use authored facts and post-peaceful sandbox state; infer no cover or paths from labels or PC position and load or repair no ambient location graph.
- MUST enforce ceilings of 20 actual SDK attempts per run (80 total, including startup, retries, and fallback), 7 user inputs per run (28 total), 12 controls per run (48 total) plus 3 health reads per run, 150 seconds per turn, 1,200 seconds per run, and 4,800 seconds total. Stop and preserve failure or blocked evidence for unexpected retry, fallback, identity drift, timeout, or cap violation; do not replace a row or treat unknown cost as known.
- MUST isolate runs under `tmp/combat_capture/`, use port 8360, `NEQ_OPEN_BROWSER=0`, and the repository virtual environment, and preserve unique bundles under `tmp/router-rollout/mapping-research/` with exact requests, context, condition facts, responses, snapshots, receipts, and labels.
- MUST retain the formal B1, D1, D4, B4 counterbalance; make no A-arm or baseline-improvement claim. The primary live verdict is the only live verification, and full research remains incomplete until actual human ratings are collected; ratings MUST NOT be fabricated.
- MUST leave existing capture gates and goldens unchanged. Do not edit core mapping/runtime, schemas, module-host assets, global model configuration, ontology, geometry engine, combat mechanics, regional implementation, client distribution, or add a gameplay runner. G7 remains BLOCKED; this change does not waive or alter combat gating and authorizes no live combat.
- The exact end-to-end comparison in one research capability is smaller and more auditable than introducing production mapping layers or separate runner infrastructure; the alternative is a documentation-only restatement, which cannot produce the authorized evidence.

## Capabilities

### New Capabilities

- `mapping-research-arena-comparison`: Defines the bounded, isolated capture and evidence contract needed to compare the approved mapping representations across P1 and P4.

### Modified Capabilities

None. No existing production behavior contract changes; the new contract is confined to research capture tooling.

## Impact

The later implementation is limited to `scripts/seed_combat_capture.py`, `scripts/capture_drive.py`, `scripts/capture_evidence.py`, and a sandbox-only bootstrap adapter if needed. It must capture all task attempts and exact prompts without changing native context, covering rewrapping behavior so no SDK retry escapes the cap. Provider outage/quota behavior is fail-closed: stop the affected run, preserve its evidence, and do not retry by substituting or extending a row. No production API, model configuration, or persisted campaign behavior is changed.

The comparison includes both the one-PC regression floor and four-PC party shape, but touches no shared runtime path; production compatibility is unchanged. The report and review materials remain explicitly provisional until primary review of live bundles and actual human ratings.
