# Task 4.3 G5 Verdict

Date: 2026-10-24
Verdict: FAIL

## Inputs

- P1 before: `g5-before-p1-1792784264000`
- P1 after: `g5-after-p1-1792793032000`
- P4 before: `g5-before-p4-1792784380000`
- P4 after: `g5-after-p4-1792793108000`
- Comparison: `tmp/router-rollout/g5/g5-comparison.json`
- Primary verdict: `tmp/router-rollout/g5/g5-verdict.json`

All four bundles matched on provider/model, fixture, seed, and measurement method. Comparison report automated status is FAIL with no blocking reasons. Work-only timing gates targets; quiet-window timing is display-only.

## Targets

Observed/operator/threshold/status are copied from comparison `targets[]` entries. Repeated fast-call rows are retained as reported.

| Target | Party | Observed | Operator | Threshold | Status |
|---|---:|---:|---|---:|---|
| pc_action_llm_p50_seconds | P1 (1) | null | <= | 8.0 | NOT_APPLICABLE |
| pc_action_fast_p50_seconds | P1 (1) | 0.053172 | < | 1.0 | PASS |
| pc_action_fast_provider_calls | P1 (1) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P1 (1) | 0 | <= | 1 | PASS |
| enemy_batch_provider_calls | P1 (1) | 4 | == | 1 | FAIL |
| enemy_batch_p50_seconds | P1 (1) | 22.101981 | <= | 15.0 | FAIL |
| file_writes_per_combat_turn | P1 (1) | 6 | <= | 3 | FAIL |
| p1_no_latency_regression | P1 (1) | 0.053172 | <= before*1.10 | 0.107881 | PASS |
| p1_no_provider_call_regression | P1 (1) | 4 | <= before | 2.0 | FAIL |
| p1_no_file_write_regression | P1 (1) | 9 | <= before | 9.0 | PASS |
| phase_provider_calls_no_increase | P1 (1) | 0 | <= | 0 | PASS |
| phase_file_writes_no_increase | P1 (1) | 0 | <= | 0 | PASS |
| phase_provider_calls_no_increase | P1 (1) | 2 | <= | 0 | FAIL |
| phase_file_writes_no_increase | P1 (1) | 0 | <= | 0 | PASS |
| pc_action_llm_p50_seconds | P4 (4) | null | <= | 8.0 | NOT_APPLICABLE |
| pc_action_fast_p50_seconds | P4 (4) | 0.05715 | < | 1.0 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| pc_action_fast_provider_calls | P4 (4) | 0 | <= | 1 | PASS |
| enemy_batch_provider_calls | P4 (4) | 2 | == | 1 | FAIL |
| enemy_batch_p50_seconds | P4 (4) | 18.894906 | <= | 15.0 | FAIL |
| file_writes_per_combat_turn | P4 (4) | 7 | <= | 3 | FAIL |
| p4_round_latency_improvement | P4 (4) | 0.325668 | >= | 0.3 | PASS |
| phase_provider_calls_no_increase | P4 (4) | 0 | <= | 0 | PASS |
| phase_file_writes_no_increase | P4 (4) | 0 | <= | 0 | PASS |
| phase_provider_calls_no_increase | P4 (4) | -1 | <= | 0 | PASS |
| phase_file_writes_no_increase | P4 (4) | 1 | <= | 0 | FAIL |

## Passed

- P4 round work-only latency improvement: 0.325668 >= 0.30 (r1 28662.749 -> 19328.22 ms).
- Fast PC action p50: P1 0.053172 s and P4 0.05715 s, both below 1.0 s.
- Fast PC actions: zero provider calls (P1 and all 24 P4 actions).
- P1 latency regression: 0.053172 <= 0.107881 s.
- P1 file-write regression: 9 <= 9.
- P4 phase provider-call delta: -1.

## Failed

- Enemy-batch provider calls: P1 4 and P4 2, versus 1 target.
- Enemy-batch work-only p50: P1 22.101981 s and P4 18.894906 s, versus <=15.0 s.
- File writes per combat turn: P1 6 and P4 7, versus <=3.
- P1 provider-call regression: 4 > before 2; one stochastic validator rejection/retry.
- P1 ENEMY_PHASE provider-call delta: +2.
- P4 ENEMY_PHASE file-write delta: +1 (two PCs damaged versus one).

## Rates

- Validation skip: P1 1/3 skipped (rate 0.333333), 2/3 LLM path; reason `low_risk_actions_only`.
- Validation skip: P4 2/3 skipped (rate 0.666667), 1/3 LLM path; reason `low_risk_actions_only`.
- NL fast path: not observed for either fixture; both scripts use slash commands and have no `pc_phase_parser` events.

## Analysis

Absolute enemy-batch targets (1 provider call, <=15s, <=3 writes) were missed by the before reference too and are structural under the approved spec: an enemy batch is always LLM-generated plus LLM-validated (2 calls minimum, validation skip forbidden for batches), and persists encounter + per-damaged-PC character + history/chat writes. Strict regressions are outcome-dependent (dice/model retry).

## Owner decision required

A. Re-ratify the three absolute enemy-batch targets for the gpt-6-luna main+validation batch shape and define how outcome-dependent strict-regression deltas are judged.
B. Authorize further hot-path scope aimed at the batch targets (for example, validation skip or merge for batches, or batch write consolidation); the spec currently forbids batch validation skip.
C. Record G5 FAIL and proceed.

## Owner disposition (2026-10-24)

The verdict stays FAIL, and the owner accepted closure as described in design D9. The three enemy-batch targets transfer unweakened to `combat-deterministic-enemy-resolution`. Outcome-dependent no-increase misses will be re-judged there using repeated runs and outcome-normalized accounting.
