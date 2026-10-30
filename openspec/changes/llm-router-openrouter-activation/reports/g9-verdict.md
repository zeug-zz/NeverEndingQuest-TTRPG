# G9 Interim Verdict

**Status: FAIL (primary interim G9 verdict)**

G7 is PASS. G9 m1 narrator P1 preflight rejected the inherited 300-second bound; the bound was fixed and independently tested with 116 tests.

For G9 m3, the P1 narrator sandbox started successfully and completed step 1. Step 2 received a game error in `main.py` when `validate_ai_response` called `strip` on `None`; the run then reached the 300-second cap. Two steps executed. This is a primary interim FAIL, not a G9 PASS.

The corrective code normalizes non-text responses into the existing bounded invalid-JSON retry/fail-open behavior. The primary focused suite reported 63 OK. This correction has not yet been rerun for the G9 verdict.

Provider log suppression and the capture checker were fixed. The primary focused suite reported 125 OK, and the old log was correctly rejected. Credential rotation remains required from the owner; no claim of rotation is made. A prior server log contains an ExchangeRate-API credential. Do not reproduce or distribute the credential, do not read actual logs/secrets, and do not edit the evidence.

Evidence (sensitive; do not share):
- `tmp/router-rollout/g9/g9m3-narrator-auto-p1/`
- `tmp/router-rollout/g9/server-g9m3-narrator-auto-p1.log`

primary G9 remains BLOCKED (full matrix incomplete). After the owner said the key was good to go, g9m4 narrator P1 produced no provider receipt or readiness by 180 seconds and executed zero gameplay steps. Diagnostic g9diag-20261028-r2 P1 reached startup and completed two travel steps, but step 3 received two structurally invalid JSON responses and produced no gameplay output within 300 seconds. No causal determination has been made.

Evidence (sensitive; do not share):
- `tmp/router-rollout/g9/g9m4-narrator-auto-p1/`
- `tmp/router-rollout/g9/g9diag-20261028-r2-narrator-auto-p1/`

g9diag-20261028-r3 narrator P1 startup did not reach readiness at 180 seconds, with zero completed provider receipts and zero gameplay steps. Primary-inspected faulthandler stack samples at 120 and 170 seconds showed `dm_main` blocked reading the HTTP response body via `httpcore` in `utils/llm_router.py`; this does not prove a specific network cause. The response metadata file was empty. Prior diagnostic r2 retained non-JSON results: one with an embedded required-key JSON object and one without; response contents were not shown and the finish reason was unavailable. Current G9 remains BLOCKED; no gate waiver was granted.

Evidence (sensitive; do not share):
- `tmp/router-rollout/g9/g9diag-20261028-r3-narrator-auto-p1/`
- `tmp/router-rollout/g9/thread-stacks-g9diag-20261028-r3-narrator-auto-p1/`
- `tmp/router-rollout/g9/response-diag-g9diag-20261028-r3-narrator-auto-p1/`

g9diag-r4 narrator-auto P1 did not reach startup readiness within 180 seconds and completed zero gameplay steps. The run was automatically marked BLOCKED, the report was degraded, response metadata was zero bytes, and the listener stopped. No causal determination has been made; G9 remains BLOCKED.

Evidence (sensitive; do not share):
- `tmp/router-rollout/g9/g9diag-r4-narrator-auto-p1/`
- `tmp/router-rollout/g9/response-diag-g9diag-r4-narrator-auto-p1/`

g9diag-r5 narrator P1 did not reach startup readiness within 180 seconds. The instrumentation was inactive in the child because the launcher had consumed the exclusive file. Sandbox-only instrumentation was fixed and covered by provider-free tests.

g9diag-r6 narrator P1 reached startup and completed the first travel step, but the persisted location remained CA01 instead of the expected CA02. The driver stopped; this run is BLOCKED, not G9 PASS. Six `dm_main` HTTP requests completed in 5.777–10.649 seconds, with response-body chunk cadence observed and a configured 120-second read timeout. This does not explain the earlier stalls; the cause of the travel mismatch is unknown.

Evidence (sensitive; do not share):
- `tmp/router-rollout/g9/g9diag-r5-narrator-auto-p1/`
- `tmp/router-rollout/g9/g9diag-r6-narrator-auto-p1/`
- `tmp/router-rollout/g9/transport-diag-g9diag-r6-narrator-auto-p1/`

g9diag-r7 narrator P1 reached startup, but step 1 hit the 300-second cap and failed. One step was sent; no further controls were issued, and the listener stopped. Sandbox-only travel metadata records model transitionLocation CA02, prevalidation approved, and response validation accepted; no apply outcome was observed by the cap. This does not establish the cause or infer the cause of r6. G9 remains incomplete.

Evidence (sensitive; do not share):
- `tmp/router-rollout/g9/g9diag-r7-narrator-auto-p1/`
- `tmp/router-rollout/g9/travel-diag-g9diag-r7-narrator-auto-p1/`

g9m6 narrator-auto P1 (after tasks 1.4-1.6): startup ready, step 1 (travel to CA02) completed in 31.7 s without timeout, but the persisted location stayed CA01 and the driver stopped; automated status BLOCKED, primary verdict FAIL for this row. With JSON mode, every routed response parsed as a JSON object. main_dm (deepseek/deepseek-v4-flash) emitted narration/actions and the transition agent (z-ai/glm-5.3-flash) approved CA01 -> CA02, but dm_validation, routed by openrouter/auto in its default low cost band to deepseek/deepseek-v4.1-flash, twice returned the DM narration/actions shape instead of the validator's valid/reason object; main.py rejected it as 'No reason provided' and the deterministic-repeat guard stopped the turn after the bounded retries. Cause: task-role adherence of the low-band Auto model for dm_validation, not format, transport, or deadline. Resolving it requires an owner decision on Auto cost tier or model pool (the design keeps both unchanged). G9 remains incomplete.

Evidence (sensitive; do not share):
- `tmp/router-rollout/g9/g9m6-narrator-auto-p1/`
- `tmp/router-rollout/g9/server-g9m6-narrator-auto-p1.log`

g9m8 narrator-auto P1, after owner-approved validator medium-tier: steps 1 and 2 persisted CA02 then CA03. Step 3 hit the 300-second timeout with no non-echo output; the run is BLOCKED/FAIL for gate purposes and the server was stopped. Primary safe-metadata analysis found two structurally invalid JSON `dm_main` responses at step 3. Fake SDK-boundary tests confirm that the JSON-contract request format is preserved in the tested Auto request; live provider behavior and root cause remain unproven. G9 remains incomplete.

Evidence (sensitive; do not share):
- `tmp/router-rollout/g9/g9m8-narrator-auto-p1/`
Primary g9m8 combat-auto:p4 capture declared 22 inputs/35 controls by mistake before execution. The G9 fixture actually allowed and executed 26 inputs/39 controls, with no timeouts, and automated status READY_FOR_PRIMARY_REVIEW. Primary treats this run as BLOCKED for gate acceptance due to the predeclared bound mismatch despite automated readiness; retain tmp/router-rollout/g9/g9m8-combat-auto-p4/ and rerun with the correct declared G9 bounds.

Primary review of the subsequent captures: combat-auto:p1 g9m8, combat-auto:p4 g9m9, transport-failure:p1 and transport-failure:p4 g9m9, and preferred-openai-rollback:p1 and preferred-openai-rollback:p4 g9m10 had no timeouts, passed required checks, and produced expected routing receipts with the same source identity. The controlled-failure captures included the injected error and one direct gpt-6-luna request. The rollback lifecycle included one restart. These row results are interim evidence only and do not establish final G9 PASS.

Narrator-auto:p4 g9m10 is FAILED/BLOCKED: step 3 reached the 300-second cap with no backend output. Safe primary structural inspection found two invalid-JSON dm_main responses, neither containing an embedded required-key object. This does not establish that the provider ignored JSON mode or prove any other cause. Narrator-auto:p1 g9m8 likewise timed out at step 3 with malformed dm_main responses. The matrix remains incomplete; automated readiness is not a verdict. G9 remains BLOCKED, not PASS.

Evidence (sensitive; do not share or inspect raw evidence/secrets):
- `tmp/router-rollout/g9/g9m8-combat-auto-p1/`
- `tmp/router-rollout/g9/g9m9-combat-auto-p4/`
- `tmp/router-rollout/g9/g9m9-transport-failure-p1/`
- `tmp/router-rollout/g9/g9m9-transport-failure-p4/`
- `tmp/router-rollout/g9/g9m10-preferred-openai-rollback-p1/`
- `tmp/router-rollout/g9/g9m10-preferred-openai-rollback-p4/`
- `tmp/router-rollout/g9/g9m10-narrator-auto-p4/`
- `tmp/router-rollout/g9/g9m8-narrator-auto-p1/`

Sandbox-only g9diag-r11 narrator-auto:p1 used opt-in `provider.require_parameters=true` on marked Auto JSON requests as a diagnostic, not a gate candidate. Steps 1 and 2 completed; step 3 timed out at 300 seconds with no non-echo output. Primary safe response-shape inspection found two invalid-JSON `dm_main` responses, both resolved to `deepseek/deepseek-v4-flash-0731`. Network request proof was unavailable, so there is no assertion that the hook reached the provider or that the provider ignored a parameter. This diagnostic establishes neither cause nor G9 PASS.

Evidence (sensitive; do not share or inspect raw evidence/secrets):
- `tmp/router-rollout/g9/g9diag-r11-narrator-auto-p1/`
- Diagnostic code: `tmp/router-rollout/g9/diag_runtime/auto_json_require_parameters.py`

g9m11 narrator-auto:p1, after the owner-approved `dm_main` medium tier, completed five gameplay steps without timeouts. The row is FAIL for G9 because startup encountered an OpenRouter transport timeout and used the direct OpenAI fallback. The raw candidate contained narrator-only encounter/combat checks incorrectly required by the evaluator; `scripts/capture_evidence.py` was corrected to use the G4 narrator state/dialogue checks while preserving strict G9 fallback policy. Primary verification reported 151 focused tests passing and ASCII compliance 0. No G9 PASS is claimed.

Evidence (sensitive; do not share or inspect raw evidence/secrets):
- `tmp/router-rollout/g9/g9m11-narrator-auto-p1/`

g9m12 narrator-auto:p1 completed five gameplay steps without timeouts, but is FAIL for G9 because startup encountered an OpenRouter `APITimeoutError` and used the direct fallback. After the evaluator was corrected for narrator applicability, the 300-second check showed no other problems. g9m12 narrator-auto:p4 is also FAIL: the same startup timeout/fallback occurred, and step 2 reached the 300-second active-processing cap, stopping the scenario. The observed transition from 07:23:39 to 07:26:13 and the subsequent adventure summary still processing at the cap do not support a causal inference. G9 remains incomplete.

Evidence (sensitive; do not share or inspect raw evidence/secrets):
- `tmp/router-rollout/g9/g9m12-narrator-auto-p1/`
- `tmp/router-rollout/g9/g9m12-narrator-auto-p4/`

Sandbox-only, non-gate isolated SDK-boundary diagnostic g9diag-20261029-r14 narrator-auto:p1 completed five turns with zero turn caps/timeouts. Startup Auto `dm_main` SDK kwargs were confirmed as `openrouter/auto`, medium tier, and JSON response format. An `APITimeoutError` occurred after 120014 ms, followed by a successful direct `gpt-6-luna` response in approximately 4 seconds; later Auto `dm_main` requests succeeded. This confirms request configuration at the SDK boundary, not a provider root cause, and the capture cannot satisfy G9. G9 remains incomplete.

Safe metadata/evidence paths (do not inspect raw logs or secrets):
- `tmp/router-rollout/g9/sdk-boundary-diag-g9diag-20261029-r14-narrator-auto-p1/sdk_boundary.jsonl`
- `tmp/router-rollout/g9/g9diag-20261029-r14-narrator-auto-p1/`

g9m13 combat-auto, transport-failure, and preferred-openai-rollback candidates passed their recorded checks with no timeouts. They produced the expected Auto routing, injected-fallback, and one-restart direct receipts, respectively. These are candidate row results only; the full primary matrix verdict remains pending and G9 is incomplete.

g9m14 narrator-auto:p1 completed five steps without timeout, cap, or fallback, with expected route snapshots and offline row readiness. It is a candidate only, not a G9 verdict. Narrator-auto:p4 completed five steps without a turn timeout or cap but is FAIL for G9 due to unexpected Auto startup transport failure and direct fallback; the evaluator reported no other problems. G9 remains incomplete.

Evidence (sensitive; do not inspect raw logs or secrets):
- `tmp/router-rollout/g9/g9m13-<row>/`
- `tmp/router-rollout/g9/g9m14-narrator-auto-p1/`
- `tmp/router-rollout/g9/g9m14-narrator-auto-p4/`

## G9 Final Verdict

**Status: PASS (primary verdict)**

The primary independently reviewed the complete eight-row live matrix and judges G9 PASS. The retained passing bundles are narrator-auto P1 `g9m14`, narrator-auto P4 `g9m15`, and combat-auto, transport-failure, and preferred-OpenAI-rollback P1/P4 `g9m13`. Full bundle paths are under `tmp/router-rollout/g9/<run-id>/`.

Primary review inspected roster, location, and actor projections; confirmed zero timeouts/caps, model/provider and actual/unpriced provenance, the single controlled paired direct fallback, rollback with exactly one restart, and owned-server lifecycle and evaluator readiness. Each full evaluator output was `READY_FOR_PRIMARY_REVIEW`; readiness is evidence, while PASS is the primary's independent judgment.

All source maps are identical except the P4 narrator bundle's `scripts/capture_evidence.py`, changed by the offline evaluator fix. Runtime hash maps are identical. Each manifest binds to its own source, and the current evaluator revalidates the original evidence; the artifacts do not assert a cross-row exact evaluator-hash requirement.

Later narrator P1 attempts `g9m15` and `g9m16` failed in separate attempts. They are retained but are not counted as passing rows and have not been erased. Transient startup timeouts and malformed output remain intermittent operational observations; this verdict does not claim they are cured.
