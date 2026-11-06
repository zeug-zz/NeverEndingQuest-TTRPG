# SP4 primary report: collection closeout and pending owner gate

**Run:** `sp3-s-20261105t200000z` · **Review:** `sp4-review-20261106-01` · **As of:** 2026-11-06
**Disposition:** collection is closed; no live row passed. The owner decision gate is pending. This report does not accept ADR-0034 or alter frozen criteria.

## Primary collection outcome

The primary attempted all 26 planned rows: **18 primary FAIL, 8 primary BLOCKED, 0 live PASS**. The immutable automated ledger and bundle audit classify all 26 as BLOCKED; that automation status is not the primary result. Twenty-five responses are ledger-bound and included in the review packet; of those, 18 are not rateable and 7 are complete-for-rating. E01's offline-recovered bundle is hash-verified but not ledger-bound and has no transcript, so it is separately excluded from the 25. The bundle audit verifies hashes for all 26, with that E01 limitation.

There were 513 attempts, 3,453.3628182079847 seconds total live time (sum of launch-to-teardown row intervals, well below 21,600 seconds), and no row exceeded 35 attempts or 1,500 seconds. Booking `sp3-s-20261105t200000z` ran 2026-11-05T20:00Z–2026-11-06T04:00Z; actual start 20:05:39Z; release 2026-11-06T02:18:55Z. Booked elapsed was 22,396 seconds, a different measure from live time. Network non-overlap was confirmed. The primary verified no port-8360 listener and restored/removed the sandbox after preserving canonical/evidence state. Port 8357 and the installed campaign were never used.

### Slot ledger (primary status; automated status is BLOCKED for every attempted row)

Each attempted row has bundle `tmp/router-rollout/mapping-pilot/row-bundles/sp3/<ID>-20261105-01`, except E01 which is the offline-recovered bundle at that path and is not ledger-bound. Primary review files are `tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/<ID>-primary-review.json`; E01 uses `E01-primary-recovery.json` and `E01-offline-finalization.json`. The full automated reasons are in `primary-collection-closeout.json`.

| Slot | Primary | Attempts | Live seconds | Primary finding / limiting reason |
|---|---|---:|---:|---|
| E01 | BLOCKED | 6 | 34.291459374988335 | 0 scripted turns; startup collector stopped and evidence namespace collided. Offline recovery completed, but original in-memory score/before-state are lost and recovered bundle is not ledger-bound. |
| E02 | FAIL | 15 | 40.896563416012214 | Asserted the unknown back-door destination was an alley; disconnect interrupted remaining turns/restart. |
| E03 | BLOCKED | 10 | 31.633165749997715 | Transport disconnect while owned worker was running; final in-flight receipt, assertions, and lifecycle checkpoint absent. |
| E04 | BLOCKED | 9 | 29.40738233299635 | Poll payload rejected after PING/PONG; no completed turns/delivery completion, despite one backend reply visible. |
| E05 | BLOCKED | 9 | 32.40782437501184 | HTTP 200 response had 22 MESSAGE packets, exceeding decoder's installed limit of 16; 0 delivered scripted turns. Primary review now exists. |
| E06 | FAIL | 17 | 168.42677116699633 | Main-loop `NameError: packet_location` at `main.py:7486`; E2-03 error was miscounted as delivered, E2-04 timed out; transition/return checks absent. |
| E07 | FAIL | 35 | 283.2289912499982 | Narrated kitchen door open despite frozen closed/unknown destination; attempt cap stopped restart/final turn. |
| E08 | FAIL | 33 | 206.86915337499522 | Party relocated to village green instead of stair viewpoint; timeout prevented door-bar/restart/return checks. |
| E09 | BLOCKED | 35 | 162.82767629199952 | Attempt cap stopped before restart/final persistence-return coverage. |
| E10 | BLOCKED | 30 | 132.84735087500303 | Checked resume matched hashes but launcher readiness refused moved MP02; final turn absent. |
| E11 | FAIL | 35 | 274.36472354199213 | 7 usable turns, 34 receipts; invented a corridor beyond the unknown back door. Checked restart was accepted and hashes matched, but the 35-attempt cap during startup prevented readiness and the final turn. |
| E12 | FAIL | 30 | 207.5782107499981 | 6 usable turns, 30 receipts; invented pot clatter, muffled curse, and bucket scrape behind the unentered kitchen door, violating authored-cues-only. E4-07 timed out; no restart/return. |
| E13 | FAIL | 26 | 191.08785091699974 | `packet_location` backend error counted as delivery, then timeout; transition/return checks absent. |
| E14 | FAIL | 28 | 209.54706208300195 | `packet_location` backend error counted as delivery, then timeout; transition/return checks absent. |
| E15 | FAIL | 31 | 263.1506736670126 | `packet_location` backend error counted as delivery, then timeout; transition/return checks absent. |
| E16 | FAIL | 16 | 171.45210204199248 | `packet_location` backend error counted as delivery, then timeout; transition/return checks absent. |
| E17 | FAIL | 31 | 227.32272654099506 | `packet_location` backend error counted as delivery, then timeout; transition/return checks absent. |
| E18 | FAIL | 29 | 196.6725635000039 | `packet_location` backend error counted as delivery, then timeout; transition/return checks absent. |
| C01 | BLOCKED | 35 | 271.0607343330048 | Goblin template missing; all monster loads failed, so real combat never started. Attempt cap also prevented final coverage. |
| C02 | FAIL | 7 | 37.743535957997665 | Combat loaded, but movement overshot the expected stair destination to the balcony; other shadow movement observations remain unknown. |
| C03 | FAIL | 9 | 37.23550504200102 | Combat movement overshot expected stairs to balcony; no valid movement observations inferred. |
| C04 | FAIL | 9 | 35.10957645799499 | Combat movement overshot expected stairs to balcony; unknown movement measures retained. |
| C05 | FAIL | 7 | 57.809838749992196 | Invented metric distances/heights where the frozen relation was near/unknown; movement evidence unavailable. |
| C06 | FAIL | 7 | 46.69993658400199 | Balcony overshoot and invented distances despite unknown metrics; no movement measures inferred. |
| C07 | BLOCKED | 7 | 69.54168837500038 | No unambiguous overshoot, but movement/round and explicit enemy-policy outcomes were unverified; driver exit 0 is not PASS. |
| C08 | FAIL | 7 | 34.1497514579969 | Explicit balcony/rail overshoot; movement measures unavailable. |
| R01 | missing | 0 | none | Unused; no live interval and no eligible pre-content INFRASTRUCTURE classification. |
| R02 | missing | 0 | none | Unused; no live interval and no eligible pre-content INFRASTRUCTURE classification. |
| R03 | missing | 0 | none | Unused; no live interval and no eligible pre-content INFRASTRUCTURE classification. |
| R04 | missing | 0 | none | Unused; no live interval and no eligible pre-content INFRASTRUCTURE classification. |

The 26 original classifications remain `UNRESOLVED` pending owner adjudication. There was no eligible infrastructure classification. No replay, replacement, or reserve activation occurred; content/result and unresolved rows were not retroactively relabeled to qualify. Reserve slots are not counted among the 26 attempted rows.

## Evidence corrections, confounds, and limits

- **E01:** recovery/finalization index `tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/E01-offline-finalization.json` records offline finalization of preserved raw live evidence; this was not a rerun. The recovered bundle is `tmp/router-rollout/mapping-pilot/row-bundles/sp3/E01-20261105-01/`. Hashes are verified, but it is unbound to the terminal ledger, has no usable transcript, and is separately excluded/not rateable. Original in-memory score, before-state snapshot, and original canonical bytes are unavailable. Its recovered score is labeled as recovered; do not imply the original score was preserved.
- **C01 / C02 tooling sequence:** C01 never executed real combat because the Goblin template was absent. Before C02, the primary verified the heavy seed/hash-parity correction and addressed a blinding false positive: 240 primary tests, 850 ASCII checks, strict validation valid. The exact source amendment was `combat-fixture` (see `identity-freeze-combat-fixture.json`). C02 onward still had real combat but did not produce a live PASS.
- **Post-collection tooling:** the default-release microsecond-precision correction and Semgrep test-execution correction (`exec` to `runpy`) passed 46 focused primary checks. External CI was not rechecked; do not claim CI green.
- Reconstructed score inputs reproduce all 26 persisted scores exactly from retained receipts/checks, but this does not restore missing original in-memory state. Chronological shadow observations were not retained; `[]` means unknown/unavailable observation history, not zero contradictions. Automated `completed` and `complete_matched_combat_rows=3` are delivery/scoring labels, not successful live gates or valid matched experiments. That count can include backend-error outputs. No valid matched live PASS exists; primary usable counts govern interpretation.
- **Q6 route confounding:** DeepSeek share differs from A by 16.8185 percentage points for B and 13.7918 points for D (estimated; threshold flag at 10 points). Route unpinning, unknown/missing route observations, and source amendments confound comparisons. These are not causal format effects.
- The report's generated outputs are not a scientific conclusion: unknown denominators remain unknown, so they cannot support a zero-contradiction or threshold claim.

## SP4 review and owner gate

The generated report at `tmp/router-rollout/mapping-pilot/sp4/sp4-report-20261106-01/decision_report.json` covers Q1–Q6 and gives all five recommendations as **inconclusive**. Q1 sense-of-place and Q5 shared-map require human ratings; Q2 format is not evaluable; Q3 zone/intent is inconclusive; Q4 backfill needs owner audit; Q6 has route/usage evidence with the confounds above. Stage 1 is **waived**, not scored.

The review packet manifest lists 25 blinded responses. The ratings sheet has 18 `not rateable` and 7 complete-for-rating responses; every score field is blank and no rating is locked. Partial blinding is disclosed because ASCII sketches can reveal format. The condition key remains withheld until owner lock and is not part of this report. E01 is separately missing/not rateable, not included in the 25.

Inputs/handoff are present: 20 D1 Builder handoff rows; S1, S2, SC1, S3, and S4 inputs; 1,048 D1 claims; 16 M1 sketches. The owner D1 audit is pending, including precision and invented-exit judgments. M1 ratings and live transcript ratings are pending. Stage 1 waiver and automated graph-validator counts do not substitute for owner ratings/audit. ADR-0034 is **Proposed**; no one has accepted it.

### Explicit owner next actions

1. Adjudicate the original `UNRESOLVED` row classifications; do not activate reserves or replay rows unless the frozen rules and owner review explicitly permit it.
2. Lock ratings only for the seven complete-for-rating responses; keep the other 18 not rateable and E01 separately excluded. Release the condition key only after that lock.
3. Supply live-transcript and M1 ratings, and complete the D1 owner audit (including precision denominator/numerator and invented exits).
4. Decide format, combat granularity/enforcement, and data pipeline from the evidence; explicitly accept or leave ADR-0034 Proposed. No default choice is inferred here.
5. Reconcile the report's unknown denominators and route/source confounds before claiming any preregistered threshold or scientific result.

Primary-owned local final integration verification is complete: `.venv/bin/python -m unittest discover -s scripts -p 'test_mapping_pilot_*.py'` — 241 tests in 12.229s, OK; `python3 scripts/check_ascii_compliance.py --summary-only` — 850 files, 0 violations; `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate v2-mapping-pilot-execution --strict` — valid; `git diff --check` — clean. The primary reports worktree status limited to approved scripts/change documentation. This verifies task 3.3 only; it is not a live PASS, owner completion, or ADR acceptance. External CI remains pending.

## Primary artifact index

- [SP3 primary collection closeout](../../../../tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/primary-collection-closeout.json)
- [SP3 final bundle audit](../../../../tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/primary-final-bundle-audit.json)
- [SP3 matrix ledger](../../../../tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/matrix_ledger.json)
- [E01 recovery](../../../../tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/E01-primary-recovery.json) · [offline finalization](../../../../tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/E01-offline-finalization.json)
- [SP4 generated decision report](../../../../tmp/router-rollout/mapping-pilot/sp4/sp4-report-20261106-01/decision_report.json)
- [SP4 review manifest](../../../../tmp/router-rollout/mapping-pilot/review/sp4-review-20261106-01/manifest.json) · [ratings](../../../../tmp/router-rollout/mapping-pilot/review/sp4-review-20261106-01/ratings.csv) · [blinding disclosure](../../../../tmp/router-rollout/mapping-pilot/review/sp4-review-20261106-01/disclosure.txt)
- Row reviews and canonical snapshots: `tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/<ID>-primary-review.json` and `<ID>-primary-canonical-state.json`; bundles are under `tmp/router-rollout/mapping-pilot/row-bundles/sp3/`.

## Later adjudication and SP3b readiness outcome

This section records later adjudication and profiling evidence. The preceding
SP3 and SP4 report remains the historical collection report; its earlier
pending/unresolved language is not the current SP3 owner-adjudication policy.

### SP3 adjudication

- Overseer adjudication `1a994608` records every main-SP3 arm comparison as
  **INCONCLUSIVE**. The seven mid-matrix re-freezes and missed
  three-consecutive-infrastructure pause remain recorded deviations, not
  waived deviations. Substantive content findings stand. Results are not pooled
  across freezes for arm comparisons; historical `UNRESOLVED` row records are
  left untouched.

### SP3b attempt and readiness

- Under the 2026-11-06T18:55:13Z ruling, one bounded, provider-free real-code
  profiling attempt was authorized. The attempt failed before seeder or
  runtime-path execution: the CLI raised `ModuleNotFoundError: No module named
  'scripts'`. The evidence reports zero attempted paths and zero accepted
  profiles. All eight fixture-party profile cases are missing, including the
  `transition_tower_approach` landscape branch (1-PC and 4-PC).
- The 96-check plan and `attempt-error.txt` were reconstructed after abort;
  neither is a prospective execution plan nor raw process stderr. They do not
  establish runtime coverage or runtime impossibility. The primary rejected
  the harness because it unconditionally stopped after the first path. Rejected
  source hashes were preserved and its untracked code/tests removed. No runtime
  attempt was repeated after the fix, and no retry is permitted without a new
  ruling.
- Primary readiness is **BLOCKED**: approved SP3B-001 through SP3B-019 are all
  missing for lack of a verified lifecycle profile, and none is permitted for
  live execution. The complete 19-row disposition is in the linked primary
  review JSON below. The program verdict remains for the Overseer to record;
  this is not a live PASS or final FREEZE.
- No server, listener, socket, port, booking, provider request, new gameplay
  content, or sandbox was used/created. Remaining budget is unchanged at 287
  attempts and 18,146.637181792015 live seconds. The main run remains 513
  attempts and 3,453.3628182079847 live seconds.

### Conditional SP4 owner handoff

- The ruling's fallback is to proceed to the SP4 owner gate using existing
  evidence after the Overseer records the outcome. No supplementary arm
  comparisons or new transcripts are authorized. All owner fields across D1's
  1,048 claim-audit rows and both rating fields across M1's 16 sketches remain
  blank. Of 25 blinded responses, 18 are not rateable
  and seven are complete-for-rating, with all owner scores blank. The condition
  key remains held until owner lock; E01 remains excluded. No owner decision,
  rating, or audit is fabricated. ADR-0034 remains Proposed.
- Retained post-attempt checks report 35 focused checks OK, 276 mapping checks
  OK in 14.221 seconds, and isolated-host checks 6 OK in 1.153 seconds. These
  are supplementary checks, not runtime or profile proof. The foundation is
  draft PR #111 (`c739d516`), not merged; H2 profiles, H3 wiring, headroom, and
  freeze are not done. Green unit checks do not establish a live PASS or a
  verified profile.
- Preserve the historical report counts (241 tests and 850 ASCII checks); do
  not overwrite them with these later supplementary checks. The retained
  primary-review JSON SHA-256 is
  `31d646f63c3bd4081be73901da03d9ab7ceda4bf235573583625879d38cf1643`;
  profile-report JSON SHA-256 is
  `75f4e9304652ebecc46390d94daa3f57f7a6eeba77840e8140610a3da2b702db`.

### Later evidence index

- [SP3b primary review](../../../../tmp/router-rollout/mapping-pilot/sp3b-profiling/20261106T194337Z/primary-review.json)
- [SP3b profile report](../../../../tmp/router-rollout/mapping-pilot/sp3b-profiling/20261106T194337Z/profile-report.json) · [attempt error](../../../../tmp/router-rollout/mapping-pilot/sp3b-profiling/20261106T194337Z/attempt-error.txt) · [rejected source index](../../../../tmp/router-rollout/mapping-pilot/sp3b-profiling/20261106T194337Z/rejected-source/index.json)
