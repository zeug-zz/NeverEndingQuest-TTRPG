# Design

## Context

See `proposal.md` for the motivation and scope. The implementation is bounded by the runtime and measurement contracts in `specs/`.

Current code already separates the relevant seams:

- `core/combat/validation.py::validate_combat_response` owns deterministic combat prechecks and LLM validation. It currently reports `skip_llm_validation=False`, uses a five-attempt validation ladder, and receives an `api_timeout_seconds` dependency.
- `core/combat/turn.py::run_combat_provider_retry_stage` prepares compressed retry context and currently invokes per-message compression on provider attempts. `apply_reported_round_transition` is the round-boundary seam; `core/combat/combat_manager.py::compress_old_combat_rounds` is the existing round-history operation.
- `core/combat/combat_manager.py` builds validation/retry dependencies and owns `sync_active_encounter`. `begin_combat_turn_iteration` calls the sync seam and separately reads turn state; the sync path also reads `party_tracker.json` and already has partial write-on-change logic.
- `core/combat/multi_pc/manager.py` owns the head context, initiative tracker, party-turn summary, PC prompt context, and PC-phase ledger renderers. `core/combat/decisions.py` already separates PC-phase eligibility from parser execution and models handled, declined, and unavailable outcomes.
- `utils/ai_client_factory.py` owns the shared client's effective timeout and supports `retry_tier`; combat must preserve that ownership rather than add a parallel provider policy.
- `utils/combat_latency_trace.py` is an opt-in fail-open observer. The existing fixtures, `scripts/capture_drive.py`, `scripts/capture_evidence.py`, and `scripts/combat_latency_report.py` provide the G3/G4 and provider-free measurement surfaces; G3 remains the driver default.

## Goals / Non-Goals

**Goals:**

- Implement only the eight Phase 2 hot-path items and the G5 evidence needed to judge them.
- Keep the latency wins measurable per captured PC action, enemy batch, phase, and turn, not just as aggregate session time.
- Preserve equivalent prompt text and authoritative transitions in both the 1-PC-party regression floor and the 4-PC fixture.
- Resolve the validator stale-view correctness defect before capturing a usable G5 before-reference, while keeping LLM validation enabled.

**Non-Goals:**

- No prompt edits, mechanic or resolver expansion, combat-state schema change, router activation, provider/model change, OpenRouter rollout, Jev implementation, or change to the accepted candidate bake-off. D8 is the approved, scoped exception to the no-prompt-edits non-goal: only the dynamic runtime validator context gains an authoritative phase block; static prompt files remain byte-for-byte unchanged.
- No commit-before-publication work from Build 6, remaining call-site migration from Build 5, or provider activation from Build 7.
- No new generalized capture framework, parallel driver, or replacement for the existing G1/G3/G4 tools.

## Contract Layer (MUST)

1. **Authority and provider ownership.** Python remains authoritative for combat state. The shared router factory remains the owner of provider timeout, transport, quota/outage recovery, and retry behavior. Combat may select a validation/reasoning retry tier but MUST NOT add a second transport or retry policy.
2. **Behavior equivalence.** Prompts, phase/round transitions, initiative, roster, death-save, enemy-batch, resume-replay, and atomic persistence invariants MUST remain unchanged. Only the call and write cadence explicitly described by the delta specs may change.
3. **Trace safety.** G5 records MUST be bounded, non-secret, and observational. Trace/report failures MUST NOT change validation, state, provider calls, or capture execution.
4. **Measurement identity.** G5 before/after evidence MUST use the same fixed fixtures: P4 uses the existing default 4-PC latency script (historical label `4 PCs x 3 rounds + 1 enemy batch`), unchanged; observed rounds, steps, and enemy batches are recorded, not asserted beyond the script. P1 uses the existing 1-PC/one-round command script unchanged. Both fixtures MUST use direct OpenAI `gpt-6-luna`, the same seed, and the same measurement method, with distinct run IDs and a source digest for each run. Archived G1 gpt-5.6-luna data remains historical and cannot stand in for the before reference.
5. **Fixed verdict.** G5 MUST use the unchanged targets: LLM PC-action p50 <= 8 seconds; deterministic PC-action p50 < 1 second; enemy `/end` batch p50 <= 15 seconds; <= 1 provider call per uncontested fast-path PC action; <= 2 per uncontested LLM-path PC action; exactly 1 per enemy batch; <= 3 file writes per turn; >= 30% lower 4-PC per-round latency than the matched before run; P1 work-only p50 no more than 10% above its matched before reference; and no increase in P1 provider calls or file writes. No measured phase may increase provider calls or writes. A fixed-target miss is FAIL; missing, incomparable, timed-out, capped, or degraded required evidence is BLOCKED. Thresholds require owner approval to change.

## Decisions

### 1. Verify timeout coverage; keep timeout ownership in the router

Audit every active combat provider site and establish that its request inherits the shared factory client's timeout or an already-required explicit bound. The manager's dependency builders currently pass `COMBAT_API_TIMEOUT_SECONDS` into combat dependencies; remove the obsolete combat-specific timeout plumbing identified by the Phase 2 audit rather than adding per-call bounds. A missing effective timeout blocks the task. Keep provider outage/quota behavior and retry recovery in the router.

**Simplest alternative considered:** add `timeout=` to each combat call. Rejected because the shared client already owns a timeout and a second bound would fork policy.

### 2. Move LLM compression to the round boundary

Remove the `process_combat_conversation` per-message/per-attempt path from the combat provider retry stage. Use the existing round-transition boundary for one LLM compression of the boundary round and deterministically truncate rounds older than the retention window. Do not add a compression provider call inside a retry. Once the active callsites are removed, delete the now-unused per-message cache files and reset/bootstrap cleanup references only after a source-wide reference check; these caches are disposable and may be regenerated if a source rollback is needed.

**Simplest alternative considered:** retain per-message compression and merely reduce the number of selected messages. Rejected because it preserves the provider-call and cache-write hot path.

### 3. Gate diagnostic dumps and remove the CWD dump

Put validation and retry per-attempt JSON dumps behind the existing debug flag. Remove the working-directory `combat_messages_to_api.json` write rather than moving it to another unconditional path. The separate opt-in latency trace remains controlled by `ENABLE_COMBAT_TURN_TRACE`, not by the debug-dump switch.

**Simplest alternative considered:** keep writing dumps and clean them after each turn. Rejected because it still incurs hot-path I/O and exposes data when diagnostics are disabled.

### 4. Add conservative validation routing at the validation boundary

Add `decide_validation_routing(...) -> (skip, reason)` in `core/combat/validation.py` after all applicable deterministic prechecks and authoritative reconciliation. Use the existing conservative policy in `utils/validation_routing.py`, extended only for deterministic-mechanics-safe combat action sets. High-risk/non-deterministic actions, failed prechecks, possession authority checks, and explicit bookkeeping corrections always use LLM validation. Cap the deterministic-failure validation ladder at two attempts; do not apply this cap to router transport/quota retries. Record the decision and reason. Reserve `jev_residual_ok`, `jev_unavailable_fallback`, and `jev_low_confidence`; do not emit them without separately authorized Jev code.

**Simplest alternative considered:** keep unconditional LLM validation. Rejected because it leaves the measured validation provider call in place; unsafe broad skipping is also rejected.

### 5. Memoize only repeated prompt renderings with complete state identity

Memoize the five existing renderers and PC-phase ledger named in the spec. Use a bounded, process-local cache keyed by `(round, phase, active_pc, encounter_revision)`. Since no durable encounter revision field exists, derive the revision token from a canonical serialization digest of the authoritative encounter object; do not add a persisted field. Tests compare each cached result byte-for-byte with a fresh render and prove a changed key cannot reuse prior output. Keep the cache local to the combat manager/session and bound its retained entries to current state keys.

**Simplest alternative considered:** cache by round alone or add a new encounter JSON revision property. Rejected because phase/active-PC/state changes can alter rendered context, while a persisted revision expands game-state schema and write ownership.

### 6. Synchronize once per turn and persist only changed encounter state

Keep synchronization at the existing turn-iteration boundary. Pass the already-loaded authoritative party-tracker snapshot into the sync path rather than re-reading it; remove the duplicate reads identified in the loop and sync function. Apply the write only when the synchronized encounter differs from the authoritative persisted state, and retain the current atomic save helper. A per-turn guard prevents a second sync invocation for the same logical turn; it does not suppress a later turn's changes.

**Simplest alternative considered:** keep the extra read/sync and suppress identical serialized writes afterward. Rejected because it retains duplicated I/O and does not meet the one-sync-per-turn contract.

### 7. Express reasoning escalation through router `retry_tier`

Keep combat's domain decision about whether a validation failure merits reasoning escalation, but pass that decision only through the existing router parameter builder's `retry_tier` interface. Do not construct a caller-owned retry or reasoning-profile override. The router continues to own provider retry, fallback, and latency attribution; timeout plumbing is handled by item 1.

**Simplest alternative considered:** construct a higher-reasoning request directly in combat. Rejected because it duplicates router profile policy and risks changing provider request semantics.

### 8. Enable the NL PC-phase canary with deterministic fallback semantics

Set `COMBAT_PC_PHASE_NL_FAST_PATH` on for the canary and use the existing `core/combat/decisions.py` eligibility seam; do not introduce party-size gates. Preserve supported attack, heal, magic-missile, and movement parsing. Record hit, miss, false-positive (recognized parse rejected by deterministic application), LLM fallback, and unavailable as separate bounded outcomes. A miss, failed application, or unavailable parser falls through to the existing LLM path. Rollback is the existing flag set to `False`.

**Simplest alternative considered:** expand parser scope or turn parse misses into hard errors. Rejected because it increases authority surface and prevents the required LLM recovery path.

### D8. Repair validator phase context before the G5 before-reference (2026-10-24)

The owner selected option B: fix the validator stale-view defect as a scoped correctness prerequisite before the G5 before-reference (group 2). The primary diagnosis found that the deterministic precheck derives live phase state and full-enemy-batch intent, but the validation message does not serialize those authoritative facts; the main combat prompt has the turn window and phase block that the validator lacks. A before-reference dominated by a five-attempt validation-retry defect would make the 30% 4-PC target measure the bug rather than a useful current-model baseline.

The approved correction is bounded to dynamic validator message assembly: include current phase, round, forbidden actors, pending enemies/current turn window, `pc_phase_complete`, `opening_batch_pending`, and `full_enemy_batch_intent` from `multi_pc_manager`/encounter state. Label the block authoritative and keep it separate from candidate claims. Do not skip LLM validation or change static prompt files. This is the sole scoped exception to the no-prompt-edits non-goal; static prompt assets remain byte-identical. G5 targets and thresholds, including the 30% 4-PC improvement target, are unchanged.

The failed bundles `g5-before-p1-1792757701000` and `g5-before-p1-1792760045000` remain `BLOCKED` historical evidence only. Neither is a passing or usable G5 before-reference.

The related `/att` hit trace omission is observational: emit the existing deterministic `combat_command_fast_path` decision with `provider_call_avoided=true` before the hit-branch return, without changing routing. For Capture_Arena only, explicitly set the existing Goblin `numAttacks` fixture field to `1` in both the 1-PC and 4-PC encounter fixtures.

### D9. Owner disposition of the G5 FAIL verdict (2026-10-24)

The primary G5 verdict is FAIL and remains FAIL; no target was changed or weakened. PASS: 4-PC round work-only improvement 32.6% (>= 30%), deterministic PC-action p50 < 1 s, 0 provider calls per fast-path PC action, and P1 work-only latency within 10% of its before reference. FAIL: enemy batch provider calls (P1 4, P4 2; target exactly 1), enemy batch p50 (22.1 s / 18.9 s; target <= 15 s), file writes per enemy batch (6 / 7; target <= 3), P1 provider-call no-increase (4 > 2, one stochastic validator rejection retry), and P4 ENEMY_PHASE write no-increase (+1, dice outcome damaged two PCs). The three enemy-batch misses are structural: every batch is one LLM generation plus one mandatory LLM validation and several saves, and the before reference missed them too.

The owner accepted closing this change with the verdict recorded as FAIL and transferred the enemy-batch call, enemy-batch p50, and per-turn write targets, unweakened, to the follow-on change `combat-deterministic-enemy-resolution` (Python-resolved enemy mechanics, one narration call, deterministic narration checks, one atomic save per batch, generate-and-validate fallback). The two outcome-dependent no-increase misses are re-judged in that change under its gate method (repeated runs with medians and outcome-normalized write/call accounting). This change makes no further runtime edits for those targets.

### G5 trace and evidence shape

Extend the current trace and capture records rather than adding a parallel system. Every G5 trace event carries `run_id`; provider and file-operation events additionally carry `action_id` for a PC action or `batch_id` for the enemy batch when applicable. Existing turn/action metadata is reused where possible; identifiers contain no message text. Capture receipts carry `work_only_ms` (accepted input to runtime processing completion) and `quiet_window_elapsed_ms` (accepted input to the driver's quiet-window completion). The report uses `work_only_ms` for target evaluation and displays both values.

No 1-PC regression is defined before capture as work-only P1 p50 within 10% of the before reference; P1 provider calls and file writes may not increase.

The G5 bundle root is `tmp/router-rollout/g5/<run-id>/`. Preserve a manifest with scenario/party/seed, source digest, provider/model, measurement method, and timestamps; verbatim driver transcript; server log; runtime trace; provider-free report; before/after state snapshots; and assertions with expected/observed values and artifact references. Before runs are captured after provider-free tooling and tasks 1b.1-1b.3 are verified, but before any group-3 runtime optimization. The primary reviews live evidence and assigns PASS/FAIL/BLOCKED; a driver exit code, mock, or builder report is never a live verdict.

## Out-of-scope follow-up for owner

The general preroll generator defect is not fixed by this change: `core/generators/generate_prerolls.py::get_monster_attacks` counts each attack-type action as an attack per turn under `CREATURE ATTACKS (exact number per creature)`. Track a separate owner-approved follow-up to correct this general inference. The scoped Capture_Arena fixtures instead set their existing `numAttacks` value explicitly to `1`; the SRD Goblin chooses one Scimitar or Shortbow attack per turn.

## Guidance Layer (SHOULD)

- Prefer focused helper changes at existing combat package boundaries; keep the large host loop as a thin integration point.
- Run each named regression module in a separate process so mutable combat globals cannot leak between suites.
- Keep trace fields enum-like and bounded, and keep provider-free report tests fully offline.
- Keep run/action/batch identifiers stable within a run; the primary SHOULD inspect each preserved bundle and judge scenario/state evidence rather than infer a verdict from driver status.
- Keep run evidence and scratch output under project-relative `tmp/`; do not alter the user's campaign or installed module.

## Risks / Trade-offs

- [Validation skip admits an unsafe action] -> Restrict skips to passed deterministic prechecks and safe action sets; test high-risk and possession negatives; retain LLM validation otherwise.
- [Memoized prompt becomes stale] -> Include round, phase, active PC, and encounter-content revision in the key; compare byte-for-byte against uncached rendering.
- [Round compression changes narrative context quality] -> Keep LLM compression at the boundary round, truncate only older rounds deterministically, and inspect matched live before/after evidence.
- [NL parser misclassifies free text] -> Record false positives, require successful deterministic application before handling, fall through to LLM on miss/application failure/unavailable, and disable via the existing flag if needed.
- [Capture quiet window masks runtime improvement] -> Preserve both work-only and quiet-window elapsed values and evaluate targets from work-only timing.
- [Provider identity changes between captures] -> Require matching direct OpenAI gpt-6-luna identity and source/fixture/seed/method evidence; otherwise mark the comparison BLOCKED.

## Migration Plan

1. Extend the existing G5 selector, bundle validation, fixture metadata, trace attribution, and provider-free report; add focused tooling tests and prove G1 output plus G3/G4 evaluation remain unchanged.
2. After tasks 1.1-1.4 and 1b.1-1b.3 are checked, the primary captures P1 and P4 before reference runs with distinct G5 run IDs and source digests before group-3 runtime edits. If either required reference is missing or degraded, stop optimization work and report BLOCKED.
3. Implement the eight Phase 2 items as separate tasks, each with focused provider-free tests and the named combat regression suites.
4. The primary captures matched P1/P4 after runs, evaluates fixed targets, records a G5 verdict, then runs the final verification suite.

### Per-item rollback

| Item | Rollback boundary |
|---|---|
| Timeout coverage | Revert the affected wiring only while retaining the shared router timeout owner; if an effective bound cannot be proven, block rather than add an unreviewed per-call policy. |
| Round compression | Revert the boundary-compression call path; the deleted cache data is disposable and will be recreated if an old consumer is restored. |
| Debug dumps | Revert only the dump-scoping implementation; retain the no-CWD-dump and no-unconditional-write safety contract. |
| Validation routing/retry cap | Return `skip=False` for all combat responses and restore the prior validation-attempt cap if the safe skip contract fails; router transport retries remain unchanged. |
| Context memoization | Bypass the cache and render fresh output; do not change prompt content. |
| Encounter sync | Revert the once-per-turn guard while preserving atomic persistence and state authority; do not suppress changed state. |
| Router retry tier | Revert the combat escalation selection to its prior router-supported shape; do not create a combat-owned provider retry/profile. |
| NL fast path | Set `COMBAT_PC_PHASE_NL_FAST_PATH=False`; all PC input returns to the existing LLM path. |

## Build Boundary

- **Build 5:** Compression-engine ownership is settled here. Build 5 may migrate remaining compression consumers to the router but SHALL NOT reintroduce per-message combat compression or expand this G5 optimization scope.
- **Build 6:** Commit-before-publication, turn receipts, replay/idempotency redesign, and code-owned round advancement remain in `combat-turn-commit-and-receipts`; this change preserves current atomic persistence and replay contracts only.
- **Build 7:** OpenRouter activation and provider/model selection remain out of scope. G5 uses direct OpenAI `gpt-6-luna` strictly as a matched measurement identity, not as a new runtime routing policy.
