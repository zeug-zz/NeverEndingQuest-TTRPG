# SP3 Live Execution Evidence

## Booking and frozen run identity

The primary booking was `sp3-s-20261105t200000z`, scheduled from 2026-11-05T20:00Z through 2026-11-06T04:00Z. The primary orchestrator was the holder; Network non-overlap was confirmed. The frozen matrix contains 26 planned rows and 4 infrastructure-only reserves. Limits are six hours/800 attempts for the matrix and 25 minutes/35 attempts per row. Live time is the sum of launch-through-teardown intervals; booking elapsed time is recorded separately.

The run used PR97 tooling head `556935d6`, rebased onto `b3950697`; original recovery branch identity `a36c25a6` was preserved. Preflight recorded 204 tests, 847 ASCII checks with zero violations, and strict validation valid.

## E01 primary verdict and correction

**E01: BLOCKED.** The primary recovery record reports 6 attempts, 34.291459 seconds live elapsed, 0 scripted turns, raw evidence saved, and the finalized bundle and score missing. The original pre-content classification remains **UNRESOLVED** for owner adjudication. No reserve was activated and no rerun was performed. Missing required finalized evidence means task 3.1 is incomplete; it is not waived.

After preserving E01, the heavy builder corrected attributable startup-collector and evidence namespace faults. The primary verified the correction with 38 execution tests and 210 full mapping-pilot tests passing, ASCII 847/0, strict validation valid, and a clean diff check. The original `identity-freeze.json` remains unchanged; `identity-freeze-collector-correction.json` records the amendment and exact patch archived before E02. Future rows continue collecting attributable startup/restart calls, but count and report deviations and cannot PASS on that basis. Unknown receipts, counters, writes, attribution, or state mismatches remain fail-closed.

For the corrected future bundle namespace, row bundles use `tmp/router-rollout/mapping-pilot/row-bundles/sp3/<row-run-id>`, distinct from the matrix runtime namespace `tmp/router-rollout/mapping-pilot/sp3/<matrix-run-id>/runtime`.

## E02 primary verdict

**E02: BLOCKED; primary verdict FAIL.** The immutable bundle records 2/8 completed turns, 15 attempts, 14 receipts, and 40.896563 seconds live elapsed. E1-02 failed because the known-unknown back-door destination was asserted as an alley (“it opens on the alley”). Manifest and canonical-state hashes were verified, and the full canonical snapshot was preserved. The original pre-content classification remains **UNRESOLVED** for owner adjudication. No reserve was activated and no replay was performed. Bundle: `tmp/router-rollout/mapping-pilot/row-bundles/sp3/E02-20261105-01`.

## E03 primary verdict

**E03: BLOCKED.** The immutable bundle records 0/8 completed turns, 10 attempts, 9 receipts, and 31.633166 seconds live elapsed. A `transport_error` socket disconnect occurred while the owned worker was still running, before owned teardown; the final in-flight receipt, scripted assertions, and lifecycle checkpoint are missing. Bundle and canonical-state hashes were verified. The original pre-content classification remains **UNRESOLVED** for owner adjudication. No reserve was activated and no replay was performed. Bundle: `tmp/router-rollout/mapping-pilot/row-bundles/sp3/E03-20261105-01`.

Before E03, `identity-freeze-socket-diagnostics.json` recorded a diagnostic-only metadata amendment. The heavy patch's primary verification was 213 tests passing, ASCII 848/0, and strict validation valid. This does not establish that the underlying transport root cause is fixed.

A transport-only idle check recorded healthy PING/PONG with no `start_game`, player inputs, or provider calls; canonical state and counts were unchanged. This is diagnostic only, not a gameplay/matrix sample or replacement, and cannot establish a gameplay result.

## E04 primary verdict

**E04: BLOCKED.** The primary review records 9 attempts, 9 receipts, 29.407382 seconds live elapsed, and zero completed turns, although one backend reply was visible before disconnect. The client rejected the polling payload after PING/PONG while the owned worker was running. Bundle and canonical-state hashes were verified. Original pre-content classification remains **UNRESOLVED**; no reserve or replay was used. Evidence: `tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/E04-primary-review.json`.

Before E04, the original preflight refused the landscape pair before any seed, launch, or attempt. The narrow default-builder fix was verified with 215 tests; the exact frozen two fixtures were accepted, with no preregistration changes. The refusal/fix does not alter E04's blocked result or authorize replay.

## E05 polling-shape evidence (primary review pending)

E05: **BLOCKED**, with 9 attempts, 9 receipts, 32.407824 seconds live elapsed, and 0 completed turns. Do not treat this as a finalized primary review or invent a factual verdict. Metadata `tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/E05-polling-shapes.json` records an HTTP 200 response of 3931 bytes containing 22 MESSAGE packets; the installed Engine.IO decoder default is 16, and decoding reports `too_many_packets`. This evidence supports no cap or slow-generation inference. The original **UNRESOLVED** classification is preserved; no reserve or replay occurred.

The heavy scoped correction was verified by the primary with 222 tests passing, ASCII 848/0, strict validation valid, and clean diff. `SocketScriptDriver` uses only the existing `CaptureSession`; within its owned scope it temporarily sets the process-global Engine.IO message-packet limit to 64, refuses 65 and overlapping ownership or an unexpected prior bound, and restores 16 after reader stop, close, or startup failure. The class attribute is confined to the dedicated capture-driver process, not the server or product configuration; residual same-process clients would observe 64 during that scope. No dependency, server, prompt, fixture, script, provider cap, reconnect, or retry changes were made. Future captures require an identity amendment; no successful rerun or root-fix live PASS exists.

## E06 primary verdict

**E06: BLOCKED; primary observed runtime FAIL.** The immutable bundle `tmp/router-rollout/mapping-pilot/row-bundles/sp3/E06-20261105-01` records 17 issued attempts and 17 receipts; live elapsed time was 168.426771 seconds. E2-01 and E2-02 produced usable completed turns. E2-03's error output was incorrectly counted as completed by the delivery collector; E2-04 had a real 90-second no-output timeout. No transition/return coverage was obtained. The bundle remains BLOCKED, with the original classification **UNRESOLVED**; no reserve or replay was used.

The runtime failed with `NameError` for `packet_location` at `main.py:7486` in `main_game_loop`, after arrival at MP03/MPA002 in a valid single-location area with empty same-area connectivity. No production fix was authorized or applied. Decoder64 remained connected until owned teardown and restoration; the primary restoration record confirmed 16. This is transport evidence only, not a gameplay PASS.

Diagnostic-only metadata records that the subprocess guard had refused execution because of copied-sandbox `PROJECT_ROOT`; a capture-only heavy correction validated the parent worktree execution source, pinned the parent capledger regardless of child cwd, made invalid bootstrap raise `SystemExit` (ordinary `sitecustomize` errors would otherwise be swallowed), and gave child calls the original non-content receipt observer. Concurrent process sequence allocation uses the canonical atomic lock and `safe_write_json`, with no-overwrite/duplicate-observer behavior. The primary recovery suite passed 225 tests in 12.074 seconds. Earlier context-tool 120-second/30-second timeouts are retained as context-tool failures, not product-failure claims; a native rerun passed after server restart. Source changes remain uncommitted and require a future identity amendment before E07.

Across E01-E06 there is no PASS: original classifications remain **UNRESOLVED**, with no reserves or replays; the matrix remains in progress.

All gate tasks remain unchecked; ADR-0034 remains Proposed and human ratings remain pending. Verification recorded: `git diff --check` and `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate v2-mapping-pilot-execution --strict`. No commits, pushes, or live reruns were performed.

No provider route, prompt, runtime, fixture, or script changes were made. Owner D1/M1/live ratings remain pending; Stage 1 is waived. ADR-0034 remains Proposed.
