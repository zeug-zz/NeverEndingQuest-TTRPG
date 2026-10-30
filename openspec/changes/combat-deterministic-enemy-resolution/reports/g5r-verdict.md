# G5R Primary Verdict

Date: 2026-10-24

Verdict: PASS

## Capture summary

| Party shape | Run IDs | Batch median | Calls / validation | Raw writes | Comparative result |
|---|---|---:|---|---|---|
| P1 | `g5r-gate2-p1-r1-1792813084000`, `g5r-gate2-p1-r2-1792813110000`, `g5r-gate2-p1-r3-1792813134000` | 3414.6 ms (<=15000) | 1 / 0 each batch | 3, 3, 2 (<=3) | p50 0.0579 s vs 0.1079 s limit; calls -1; writes -4 |
| P4 | `g5r-gate2-p4-r1-1792813157000`, `g5r-gate2-p4-r2-1792813226000`, `g5r-gate2-p4-r3-1792813294000` | 2879.2 ms (<=15000) | 1 / 0 each batch | 2, 2, 3 (<=3) | Round 1 88.5% faster (>=30%); phase deltas <=0 |

All six runs used one final source. Each bundle passed 13/13 checks with valid receipts, no timeouts or caps, resolver support in every batch, and 6/6 accepted LLM narrations. Automated report `tmp/router-rollout/g5r/g5r-gate2-verdict.json` was `READY_FOR_PRIMARY_REVIEW` with no blockers, misses, or deviations; primary review is `tmp/router-rollout/g5r/g5r-primary-review.json`. Earlier superseded runs are retained in `final-runs-superseded-1.txt` and `final-runs-superseded-2.txt`; they predate evidence-parity and narration fixes and are not the final capture set.

## Target review

| Target | Result |
|---|---|
| Supported batch narration calls | PASS: exactly 1 call and 0 validation calls per batch |
| Median batch work-only latency | PASS: P1 3414.6 ms; P4 2879.2 ms, both <=15000 ms |
| Raw gameplay/history writes | PASS: all observed batches <=3; P1 3,3,2; P4 2,2,3 |
| P1 action work-only p50 | PASS: 0.0579 s <= 0.1079 s limit |
| P1 calls and writes | PASS: calls -1; writes -4 |
| P4 round-1 improvement | PASS: 88.5% >=30% |
| Phase call/write deltas | PASS: <=0 |
| HP reconciliation | PASS |
| Transferred G5 enemy-batch targets | PASS: all three met without weakening |

## Mechanics and narration review

P4 run 3 Acheron HP reconciled 20 -> 17 -> 11 from 3 + 6 slashing damage, matching the captured snapshots. Narrations were factual against the deterministic ledger and accepted; they did not claim unsupported mechanical outcomes.

## Gate corrections

- Corrected evidence-parity observations and capture-time resolver-support checks before final review.
- Aligned the G5R P1 p50 definition with G5.
- Corrected player-facing template narration and fixed a narration-checker false positive; added `reason_detail` logging for diagnosis.

## Follow-ups

- Improve PC pronouns in narration context; shared fast-path flavor currently uses "it" in some cases.
- Consider modest narration richness improvements under `combat-tactical-brain`.
- `DETERMINISTIC_ENEMY_RESOLUTION_ENABLED` remains OFF pending a separate owner rollout decision (D8).
