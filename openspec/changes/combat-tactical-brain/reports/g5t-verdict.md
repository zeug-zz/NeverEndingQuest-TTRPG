# G5T Primary Verdict

Current status: PASS; see the Gate10 primary verdict section below. The earlier Gate9 result is retained as gate history.

Date: PLACEHOLDER

Verdict: PLACEHOLDER (PASS / FAIL / BLOCKED)

Primary reviewer: PLACEHOLDER

Final source revision: PLACEHOLDER

## Capture summary

| Party shape | Scenario | Run IDs | Batch median | Calls / validation | Raw writes | Applied plan legality | Result |
|---|---|---|---:|---|---|---|---|
| P1 | `g5t-commander-p1` | PLACEHOLDER | PLACEHOLDER ms (<=15000) | PLACEHOLDER / PLACEHOLDER | PLACEHOLDER (<=2 + distinct changed characters) | PLACEHOLDER (100%) | PLACEHOLDER |
| P4 | `g5t-commander-p4` | PLACEHOLDER | PLACEHOLDER ms (<=15000) | PLACEHOLDER / PLACEHOLDER | PLACEHOLDER (<=2 + distinct changed characters) | PLACEHOLDER (100%) | PLACEHOLDER |

## Required behavior evidence

- Commander options compared with applied resolver ledger: PLACEHOLDER
- Per-creature Disengage flight, `status=defeated`, `defeatReason=fled`, and absence from later actor/target menus: PLACEHOLDER
- Individual and near-death side surrender, `defeatReason=surrendered`, existing exit, and XP lifecycle: PLACEHOLDER
- Remaining encounter state after flight is coherent: PLACEHOLDER
- Authored cover feature, effective AC on subsequent PC attack, and cover expiration: PLACEHOLDER
- Three distinct captures per party shape on one final source revision: PLACEHOLDER
- G1/G3/G4/G5/G5R selector, identity, and evaluator compatibility: PLACEHOLDER

## Provider-free report

- Automated G5T report path: PLACEHOLDER
- Per-batch calls, validation calls, raw writes, and work-only latencies: PLACEHOLDER
- Plan legality and required behavioral assertions: PLACEHOLDER
- Absolute target misses, deviations, and report diagnostics: PLACEHOLDER

## Optional standing-orders prefetch sub-gate

- Run IDs and status: PLACEHOLDER (not run / PASS / FAIL / BLOCKED)
- Initial/re-plan background request counts by batch and site attribution: PLACEHOLDER
- Completed, failed, cancelled, expired, unavailable, and not-requested outcomes: PLACEHOLDER
- Synchronous and background request counts reported separately: PLACEHOLDER

## Evidence bundles and review

- P1 evidence: `tmp/router-rollout/g5t/<run-id>/` (replace with exact run paths)
- P4 evidence: `tmp/router-rollout/g5t/<run-id>/` (replace with exact run paths)
- Primary review artifact: PLACEHOLDER
- Deviations, blockers, and disposition: PLACEHOLDER

The automated report is evidence, not the primary verdict. Do not record PASS unless all six required captures and assertions are reviewed. A G5T PASS supports a separate rollout decision and does not change shipped defaults.

## Gate9 primary verdict (pre-6.1, prefetch disabled)

Verdict: PASS (primary-judged by orchestrator) for the prefetch-disabled primary path. Provisional for tasks 7.1/7.2 because tasks 6.1/6.2 are not yet implemented; a confirmatory six-run gate after 6.1/6.2 is required before checking 7.1/7.2.

### Runs

Capture_Arena sandbox `tmp/combat_capture`, port 8360:

- `g5t-gate9-p1-r1-1792931528000`
- `g5t-gate9-p1-r2-1792931677000`
- `g5t-gate9-p1-r3-1792931815000`
- `g5t-gate9-p4-r1-1792931951000`
- `g5t-gate9-p4-r2-1792932106000`
- `g5t-gate9-p4-r3-1792932250000`

Bundles are under `tmp/router-rollout/g5t/<run-id>/`. Evaluator output: `tmp/router-rollout/g5t/gate9-eval.json` and `tmp/router-rollout/g5t/gate9-eval.err`; `scripts/capture_evidence.py --gate g5t` status was READY_FOR_PRIMARY_REVIEW with no blocking reasons.

### Observed

- 212 report rows all PASS.
- 30 commander batches each used <=2 provider calls (1 plan, 1 narration, 0 validation) and stayed within the raw write budget.
- Applied-choice legality was 100% in 29/29 batches with applied model choices. Median work-only latency: P1 6235.665 ms; P4 8595.556 ms (target <=15000).
- Every run observed cover applied, cover effective AC, cover expiration, fled (2/run), and surrendered (1/run) with target removal; `commander_squad_follows_orders` PASS.

### Deviation

P4 r1 batch-step-034 (enemy:r4): the plan returned an order with empty choices for the lone actor -> `rejected_all` / `MISSING_CHOICE`; Python applied the rule-tier default. The batch was accepted, with no legality row because no model choice was applied. This is spec-sanctioned fail-open, recorded as a prompt-quality follow-up, not a gate failure.

### Gate history

Gate4-gate8 were BLOCKED (early side surrender; cover evidence tooling; flee/surrender not observed). Fixes: E/F/H, narration validator, cover-as-movement, flee doctrine, exit-closing batch, cover-compatible attacks, and lone-commander surrender guidance.

## Gate10 primary verdict (final, post-6.1/6.2, prefetch disabled): PASS

- Runs (one source revision, isolated tmp/combat_capture, port 8360): g5t-gate10-p1-r1-1792962660000, g5t-gate10-p1-r2-1792962803000, g5t-gate10-p1-r3-1792962960000, g5t-gate10-p4-r1-1792963088000, g5t-gate10-p4-r2-1792963238000, g5t-gate10-p4-r3-1792963395000; bundles under tmp/router-rollout/g5t/<run-id>/; run list tmp/router-rollout/g5t/gate10-runs.txt.
- Provider-free comparison: `scripts/capture_evidence.py --gate g5t --after ...` exit 0, status READY_FOR_PRIMARY_REVIEW, no blocking reasons; output tmp/router-rollout/g5t/gate10-eval.json and gate10-eval.err.
- 30/30 commander batches PASS for: <=2 provider calls, ==1 plan call, ==1 narration call, 0 validation calls, raw writes within budget, 100% applied-choice legality. All 30 tactical plans accepted (no rejected_all).
- Median work-only latency: P1 5673.824 ms, P4 8830.249 ms (target <=15000).
- Cross-run coverage per party shape: flee 6/6 runs PASS, cover effective-AC 6/6 PASS, cover expiration 6/6 PASS, commander_squad_follows_orders 6/6 PASS, surrender 5/6 PASS (g5t-gate10-p1-r2 NOT_OBSERVED, permitted by the per-run rule since P1 r1 and r3 observed it).
- Prefetch sub-gate: COMBAT_TACTICAL_PREFETCH_ENABLED was off for primary acceptance; all traces show prefetch_status=prefetch_none; optional prefetch captures not run (optional per spec).
- Final verification: 8.1 = 72 separate processes (62-process baseline from tmp/router-rollout/g5r/final/final-6-1-results.json plus 10 new tactical modules), 1322 tests, 0 skipped, no count decreases; manifest tmp/router-rollout/g5t/final/final-8-1-results.json. One inventory expectation in scripts/test_combat_latency_hot_path.py was updated to list the approved D6 router site `prefetch_llm_call`. 8.2 = py_compile OK on touched files; standing-orders/encounter/monster/location schemas Draft7-valid; 9/9 static prompt hashes unchanged; G1 4/4 byte-identical to tmp/router-rollout/g5r/task32-g1-before; G3 50/50 identical, G4 pinned identical; ASCII 1195 files 0 violations; git diff --check clean; strict openspec validation valid. DETERMINISTIC_ENEMY_RESOLUTION_ENABLED, COMBAT_TACTICAL_BRAIN_ENABLED and COMBAT_TACTICAL_PREFETCH_ENABLED remain False pending separate rollout approval.
