# N3 Live Gate v4 Startup Diagnosis

## Ruling

This report records item 3 of ruling
`neq-n3-attempt7-cap-breach-20261114`. It documents the L03 contract correction
from `n3-live-lifecycle-v3` to `n3-live-lifecycle-v4`. It is not a live-gate
verdict or authorization to run the gate.

## Attempt-7 preparation artifacts and live failure evidence

The local attempt-7 preparation artifacts remain unchanged at
`tmp/router-rollout/v2-network/n3/start-game-proof/attempt7-prep-20261114/`.
`preintegrate.json` reports PASS; `proof.json` reports PASS with zero ledger
reservations and zero router calls, and records one provider-function call
intercepted by the offline tripwire. `tmp/n3-attempt7-prove.log` contains the
`ProviderCallBlocked` tripwire trace and ends with the proof's PASS result.
These are provider-free preparation/proof records, not a live provider-spend
receipt or a live-gate failure verdict. They are separate from the live
attempt-7 failure evidence below.

The v3 live capture
`n3-20261113-203902-646` remains unchanged under
`tmp/router-rollout/v2-network/n3/n3-20261113-203902-646/capture/`. Its
`summary.json` records gate FAIL, L01-L02 PASS, and L03 FAIL with
`startup_narration_receipt_invalid`; L04-L10 are fail-fast BLOCKED. Its
`run.json` and `provider-attempt-ledger.jsonl` record one reservation and one
`budget_exhausted` refusal under the v3 budget of one attempt. Teardown completed.
Ruling `neq-n3-attempt7-cap-breach-20261114` identifies this capture as attempt
7 and the live failure evidence. The live failure and the separate PASS
preparation/proof artifacts above remain unchanged and are not conflated.

## Root cause and accepted startup sequence

`main.py:5020-5022` calls `predict_actions_required(user_input)` before the
narration path. `utils/action_predictor.py:148` implements that prediction as
`llm.call(task="action_prediction")`; the later startup narration call is
`dm_main` at `main.py:5300`. Thus `start_game` legitimately invokes two distinct
tasks in this exact order. The v3 L03 contract allowed only one provider
attempt and required a `dm_main` receipt, so it could not represent the
observed startup sequence.

The v4 contract and driver now permit exactly one attempt each for
`action_prediction`, then `dm_main`, both on `n3-luna`, with fallbacks and
retries disabled. Both ordered receipts must be complete and priced, and both
reservations must be inside the L03 startup window. Their combined cost is
checked against the unchanged USD 0.05 per-run cap. The unchanged USD 1.00
cumulative narration cap continues to sum `dm_main` receipts.

## Provider-free diagnostic evidence

The three existing startup diagnostics all report PASS:

| Run | Trace order | Startup output | Provider calls / reservations | Network attempts |
| --- | --- | --- | --- | --- |
| `startup-diag-12` | `action_prediction` at `utils/action_predictor.py:148`, then `dm_main` at `main.py:5300` | Delivered | 0 / 0 | 0 |
| `startup-diag-13` | `action_prediction` at `utils/action_predictor.py:148`, then `dm_main` at `main.py:5300` | Delivered | 0 / 0 | 0 |
| `startup-diag-14` | `action_prediction` at `utils/action_predictor.py:148`, then `dm_main` at `main.py:5300` | Delivered | 0 / 0 | 0 |

Each trace reports both calls on the background startup thread, successful
coverage, and a stopped startup thread. Runs 13 and 14 also have passing
provider-free preintegration reports. The source artifacts remain under
`tmp/router-rollout/v2-network/n3/start-game-proof/startup-diag-{12,13,14}/`.
These diagnostics use bounded offline router stubs; they are not priced live
receipts and do not establish a live-gate PASS.

## IPv6 diagnostic limitation

The offline diagnostic sets `socket.has_ipv6` to false before the guarded
imports and keeps the patch active throughout guarded diagnostic execution
(`scripts/n3_start_game_offline_proof.py:4183-4186`). Guarded cleanup calls
`patches.restore()` (`scripts/n3_start_game_offline_proof.py:4591`), restoring
the original value. This suppresses urllib3's IPv6 capability probe for the
diagnostic, not only during import, and avoids an unneeded `::1:0` bind while
the other egress and process guards remain active. Consequently, these three
diagnostics do not establish IPv6 capability or validate an IPv6 listener path.
No such IPv6 claim is made by this evidence.
