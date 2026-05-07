# Narrator and Combat Stabilization Plan

**Status:** Archived and superseded by `openspec/changes/archive/2026-05-07-tt-deterministic-combat-death-saves/`  
**Priority:** High (Gameplay Integrity)  
**Effort:** Large (~3-5 focused implementation passes)  
**Created:** 2026-05-06  
**Source:** Expanded review of `plans/dm-narration-guard.md` after GPT 5.4 Mini gametesting

**Archive note:** This broader stabilization plan supersedes `plans/dm-narration-guard.md` and was superseded in turn by the deterministic combat death-saves OpenSpec work. It is retained for historical traceability.

## Objective

Stabilize the narrator and multi-PC combat runtime after recent gametesting exposed repeated state desynchronization, prompt contradiction, and deterministic-mechanics replay bugs.

The goal is not to add more prompt text everywhere. The goal is to reduce contradiction, centralize authority boundaries, and make Python the single deterministic gate for mechanical truth while allowing GPT 5.4 Mini to narrate creatively inside those boundaries.

Core principle:

> Python enforces reality; the LLM interprets it.

## Executive Summary

`plans/dm-narration-guard.md` identifies several real bugs, but its framing is too narrow. The current issue set is not two independent desync patterns. It is a broader narrator/combat authority problem with at least six confirmed defect classes:

1. Unsafe same-module location writes through `updatePartyTracker`.
2. Scene followers not syncing location after party transitions.
3. Scene followers not appearing in DM Note truth surfaces.
4. Combat ENEMY_PHASE prompts containing contradictory active-PC override instructions.
5. Fast-lane `/dmg` messages being reinterpreted as fresh LLM damage.
6. Combat exit precheck rejecting correct same-response enemy defeat plus `exit`.

The overhaul should be implemented as a staged stabilization chain:

1. Add a central action normalization and fail-closed tracker merge guard.
2. Repair scene follower mechanical truth and narrator visibility.
3. Remove combat phase prompt contradictions.
4. Protect deterministic fast-lane combat actions from LLM replay.
5. Simulate proposed enemy ops before rejecting combat exit.
6. Audit GPT 5.4 Mini shim, retry, timeout, and prompt parity behavior.

## Current Architecture Risks

### Risk 1: Action Authority Is Split Across Too Many Places

Narrator output, travel sync guards, inferred narrated-arrival recovery, location exclusivity logic, and action processing can all produce or mutate action lists.

Current behavior includes these action producers:

- Raw LLM JSON from `get_ai_response()` in `main.py`.
- Pre-validation travel reconciliation in `main.py`.
- Inferred travel actions from `utils/travel_state_sync_guard.py`.
- NPC arrival and scene-presence guards.
- Direct `process_action()` handling in `core/ai/action_handler.py`.
- Low-level tracker merge in `utils/party_tracker_merge.py`.

The current pre-processing fix for same-module `updatePartyTracker` misuse exists only in `main.py` and only catches the case where both `currentLocationId` and `module` are present. It misses no-module same-module location writes and any action inserted after that pre-pass.

Required direction:

- Add one shared action-normalization layer that every final action list must pass through before processing.
- Make the merge layer fail closed on unsafe location writes so bypasses cannot silently corrupt `party_tracker.json`.

### Risk 2: Prompt Text Says One Thing, Runtime Does Another

Examples:

- `@FOLLOWER_STATE` says follower location changes use `moveBackgroundNPC`, but scene followers are persisted in `data/runtime/scene_followers.json` and updated through `updateSceneFollower` helpers.
- `updatePartyTracker` prompt wording still describes module/area/location updates broadly, which encourages GPT 5.4 Mini to use it as a same-module location setter.
- Combat prompt text says phase state overrides turn logic, but the injected runtime block can still include `CRITICAL OVERRIDE: Only [PC] can act now` during ENEMY_PHASE.

Required direction:

- Narrow prompt contracts to reflect actual runtime authority.
- Remove contradictory blocks at the source rather than relying on the model to infer precedence.

### Risk 3: Combat Fast-Lane Python Actions Are Fed Back As Ambiguous User Instructions

The `/att` and `/dmg` command path applies mechanical effects deterministically, then appends human-readable system messages to combat history. The current `/dmg` message resembles an unresolved combat event rather than an already-applied state result.

GPT 5.4 Mini can interpret this as a prompt to emit more `updateEncounter` ops, causing duplicate enemy damage.

Required direction:

- Mark deterministic command messages as `[ALREADY_APPLIED]`.
- Change wording from `HP: X/Y` to `Result HP: X/Y`.
- Add prompt and validation guards that prohibit HP/state ops for already-applied fast-lane messages.

### Risk 4: Combat Validation Checks Current State, Not Proposed State

`utils/combat_phase_integrity_precheck.py` Guard 3 currently rejects any `exit` while current encounter data contains living hostiles. That is correct when the LLM tries to exit early. It is wrong when the same response contains `updateEncounter.ops` that kill the final hostile before `exit` executes.

Required direction:

- Build a conservative post-ops simulation for supported enemy ops.
- Allow `exit` only if simulated post-response state has no living hostiles.
- If simulation is indeterminate and current state still has living hostiles, block rather than fail open.

### Risk 5: GPT 5.4 Mini Needs Cleaner, Lower-Contradiction Context

GPT 5.4 Mini can perform well when instructions are compact and non-conflicting. It performs poorly when late prompt sections contradict earlier authority blocks, or when old compatibility paths remain visible as valid alternatives.

Required direction:

- Reduce competing turn indicators.
- Prefer one authoritative phase block.
- Keep compatibility paths in validators only where needed, not as equally loud instructions in generation prompts.
- Verify GPT-5-family chat params are applied consistently across narrator and combat paths.

## Confirmed Findings From `dm-narration-guard.md`

### Finding A: No-Module `updatePartyTracker` Location Desync

**Status:** Correct, incomplete fix plan.

Observed problem:

- Party transitions correctly with `transitionLocation`.
- On a later turn, the LLM emits `updatePartyTracker` with `currentLocationId` but no `module`.
- Existing pre-processing only converts same-module tracker writes when `currentLocationId` and `module` are both present.
- `_merge_party_tracker_updates()` writes location keys directly to `worldConditions`.

Plan adjustment:

- Do not rely only on the `main.py` pre-processing loop.
- Add a shared sanitizer and run it immediately before `process_ai_response()` or equivalent action processing.
- Add a hard guard in `_merge_party_tracker_updates()` or the `ACTION_UPDATE_PARTY_TRACKER` branch so unsafe same-module location changes cannot persist even if sanitizer is bypassed.

### Finding B: Scene Followers Do Not Move With Party Transitions

**Status:** Correct, needs policy refinement.

Observed problem:

- `transitionLocation` updates `party_tracker.json`.
- It does not update `data/runtime/scene_followers.json`.
- Present followers such as captured guides remain mechanically anchored to the old location.

Plan adjustment:

- Sync only followers whose state implies travel with the party.
- Do not blindly move every `lifecycle_state == "present"` follower because some present entities may be location-bound observers, guards, apparitions, or scene anchors.

Initial sync eligibility should include conservative signals:

- `visible_in_strip == True` and current location equals old party location.
- `disposition` in `guarded_guide`, `following`, `captive`, `held`, `parleying`, `companion`, `escorted`.
- `entity_type` is not a known location-bound scene-only entity.

Future extension:

- Add explicit metadata such as `travels_with_party` if scene follower state schema is later extended.

### Finding C: Scene Followers Missing From DM Note

**Status:** Correct, should be a dedicated section.

Observed problem:

- DM Note party NPC section is built from `party_tracker.json -> partyNPCs` only.
- Monster-type scene followers are visible in GUI/runtime guards but not visible to the narrator.

Plan adjustment:

- Add `--- SCENE FOLLOWERS PRESENT HERE ---` rather than hiding them inside Party NPCs only.
- Include compact fields: display name, entity type, disposition, current location, combat-validity hint.
- Emit section even when `partyNPCs` is empty.

### Finding D: Combat Opening Enemy Batch Prompt Contradiction

**Status:** Correct, with current-code nuance.

Observed problem:

- During ENEMY_PHASE, prompt context says PCs are forbidden actors.
- The same prompt can include `[>] PC - CURRENT TURN` and `CRITICAL OVERRIDE: Only [PC] can act now`.
- GPT 5.4 Mini may ask the active PC what they do or skip enemy batch resolution.

Plan correction:

- The current `required_response` block appears after the conflicting multi-PC status in `combat_manager.py`, so this is not only a recency issue.
- The root issue is contradictory authority signals.

Required fixes:

- `format_pc_context_for_prompt()` returns empty or phase-note during ENEMY_PHASE.
- `format_party_turn_summary()` suppresses active-PC marker during ENEMY_PHASE.
- `_get_combatant_marker()` suppresses `[>] CURRENT TURN` for PCs during ENEMY_PHASE.
- Combat prompt text says `[>]` is meaningful only during PC_PHASE.

### Finding E: Double Damage From `/dmg` System Messages

**Status:** Correct, high priority.

Observed problem:

- Python applies damage deterministically.
- Combat history receives an ambiguous system message.
- LLM emits fresh enemy HP ops for the same damage.
- Enemy HP is reduced twice.

Required fixes:

- Change deterministic command logs to `[ALREADY_APPLIED]`.
- Use `Result HP` wording.
- Add generation prompt directive.
- Add validation/precheck guard for duplicate fast-lane damage ops.

### Finding F: Combat Exit Precheck Blind To Same-Response Enemy Defeat

**Status:** Correct, simulation must be conservative.

Observed problem:

- Response includes `updateEncounter.ops` killing final hostile and `exit`.
- Guard 3 sees current encounter state only and rejects because the hostile is alive before applying ops.

Plan correction:

- Do not use `_safe_int(..., default=0)` in a way that could accidentally allow exit on malformed ops.
- Use strict parsing. If required HP/status values are malformed, return indeterminate.
- If current state has living hostiles and simulation is indeterminate, block exit.

## Proposed Implementation Phases

## Phase 1: Central Action Normalization And Tracker Guard

### Goal

Prevent unsafe same-module location mutation through `updatePartyTracker` regardless of where the action originated.

### Files

- `main.py`
- `core/ai/action_handler.py`
- `utils/party_tracker_merge.py`
- New or existing utility, recommended: `utils/action_normalization.py`
- `prompts/system_prompt_compressed.txt`
- `prompts/system_prompt.txt`
- `prompts/validation/validation_prompt_compressed.txt`
- `prompts/validation/validation_prompt.txt`

### Implementation Tasks

1. Add shared normalization helper.

Recommended function:

```python
def normalize_action_list_for_authority(
    actions: List[Dict[str, Any]],
    party_tracker_data: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Normalize unsafe or ambiguous action usage before processing."""
```

The helper should:

- Convert same-module `updatePartyTracker{currentLocationId}` to `transitionLocation` when target differs from current location.
- Strip no-op location fields when target equals current location.
- Preserve non-location tracker updates such as `resolvedHostilesByLocation` and nested safe `worldConditions` markers.
- Preserve valid cross-module `updatePartyTracker{module: ...}`.
- Return structured normalization events for debug logging and tests.

2. Run the helper after every final action list mutation.

Required call sites:

- Current `main.py` pre-processing location.
- Immediately after validation/inferred action insertion and before action processing.
- Any path that processes action arrays without passing through the normal narrator retry loop.

3. Harden `_merge_party_tracker_updates()`.

Add an optional authority context:

```python
def _merge_party_tracker_updates(
    current_party_data: Dict[str, Any],
    parameters: Dict[str, Any],
    *,
    current_module: Optional[str] = None,
    allow_same_module_location_write: bool = False,
) -> Dict[str, Any]:
```

Fail closed if:

- `currentLocationId` changes.
- `module` is missing or equals current module.
- `allow_same_module_location_write` is false.

The failure should produce structured error data, not only a warning.

4. Update `ACTION_UPDATE_PARTY_TRACKER` handling.

- Pass `current_module` into merge helper.
- Handle unsafe merge failure by returning a user-safe system error and not writing `party_tracker.json`.

5. Tighten prompt wording.

Change `updatePartyTracker` contract from broad location setter to:

- Cross-module travel and module activation.
- Tracker-only world flags such as `resolvedHostilesByLocation`.
- Not for same-module movement.

Same-module movement must use `transitionLocation`.

### Tests

Add or extend `scripts/test_update_party_tracker_merge.py` and narrator source-contract tests:

- `test_upt_no_module_diff_location_converts_to_transition`
- `test_upt_no_module_same_location_strips_location_keys`
- `test_upt_preserves_resolved_hostiles_when_stripping_location_noop`
- `test_upt_merge_rejects_same_module_location_change_without_bypass`
- `test_upt_cross_module_tracker_update_allowed`
- `test_inferred_travel_actions_pass_through_normalizer_after_validation`
- Prompt source test: `updatePartyTracker` is not described as same-module travel.

### Acceptance Criteria

- No same-module location change can be persisted via `updatePartyTracker` unless an explicit deterministic bypass is used.
- Existing cross-module travel still works.
- Resolved hostile markers still merge non-destructively.

## Phase 2: Scene Follower Truth Synchronization

### Goal

Ensure scene followers that are traveling with the party remain mechanically co-located with the party and visible to narrator truth surfaces.

### Files

- `core/ai/action_handler.py`
- `utils/scene_follower_state.py`
- `utils/multi_pc_dm_note.py`
- `utils/narrator_location_exclusivity_guard.py`
- `utils/npc_arrival_validator.py`
- `prompts/system_prompt_compressed.txt`
- `prompts/system_prompt.txt`

### Implementation Tasks

1. Add follower sync helper.

Recommended function in `utils/scene_follower_state.py`:

```python
def sync_traveling_followers_to_location(
    old_location_id: str,
    new_location_id: str,
    *,
    reason: str = "transitionLocation",
) -> Dict[str, Any]:
    """Move only followers that semantically travel with the party."""
```

It should:

- Load follower store.
- Select only present followers currently at the old location.
- Apply conservative travel eligibility rules.
- Move eligible followers to the new location.
- Save atomically.
- Return summary: moved, skipped, errors.

2. Call helper after successful `transitionLocation`.

Preferred placement:

- After `location_manager.handle_location_transition()` succeeds and updated `new_location_id` is known.
- Before transition narration is saved, so subsequent context is aligned.

3. Add DM Note scene follower section.

Add compact section after Party NPCs or before Location Context:

```text
--- SCENE FOLLOWERS PRESENT HERE ---
Corrupted Ranger Thane (monster, guarded_guide, currentLocation=NC05): present with party; valid scene participant; not a PC.
```

Rules:

- Include only `lifecycle_state == present`.
- Include only `current_location == effective_location_id`.
- Emit section even when `partyNPCs` is empty.
- Keep entries bounded and ASCII.

4. Fix prompt contract.

Update `@FOLLOWER_STATE`:

- Remove instruction that follower locations are changed via `moveBackgroundNPC`.
- State that follower records are managed by Python and `updateSceneFollower` creates or updates follower persistence.
- State that followers in the DM Note are valid present-scene participants.

5. Teach NPC arrival validation about `updateSceneFollower`.

If narration grounds a named scene follower as present and the action list contains matching `updateSceneFollower`, count it as valid durable state support.

### Tests

New file: `scripts/test_scene_follower_transition_sync.py`.

Cases:

- `test_traveling_follower_moves_on_transition`
- `test_location_bound_present_follower_does_not_move`
- `test_removed_follower_does_not_move`
- `test_multiple_eligible_followers_move`
- `test_follower_at_other_location_does_not_teleport`
- `test_sync_failure_fail_open_for_transition`
- `test_dm_note_includes_present_scene_followers_without_party_npcs`
- `test_dm_note_excludes_followers_at_other_location`
- `test_npc_arrival_accepts_update_scene_follower`
- Prompt source test: `@FOLLOWER_STATE` references deterministic follower records and `updateSceneFollower`, not `moveBackgroundNPC` as location persistence.

### Acceptance Criteria

- Traveling followers remain visible in GUI and DM Note after same-module transitions.
- Location-bound scene entities are not incorrectly dragged along.
- Narrator can see follower truth in the same surface it uses for PC/NPC truth.

## Phase 3: Combat Phase Prompt Authority Cleanup

### Goal

Remove contradictory active-PC instructions during ENEMY_PHASE and simplify combat phase authority for GPT 5.4 Mini.

### Files

- `core/managers/multi_pc_combat.py`
- `core/managers/combat_manager.py`
- `prompts/combat/combat_sim_prompt_multipc_compressed.txt`
- `prompts/combat/combat_sim_prompt_multipc.txt`
- `prompts/combat/combat_validation_prompt_multipc_compressed.txt`
- `prompts/combat/combat_validation_prompt_multipc.txt`
- `scripts/test_multi_pc_combat.py`
- `scripts/c5_regression_combat.py`

### Implementation Tasks

1. Make active-PC context phase-aware.

`format_pc_context_for_prompt(pc_name)`:

- During PC_PHASE: emit current critical override.
- During ENEMY_PHASE: return empty string or a non-action note such as `PC actions are forbidden during ENEMY_PHASE`.

2. Make party summary phase-aware.

`format_party_turn_summary()`:

- During PC_PHASE: current behavior.
- During ENEMY_PHASE: no `[>]` marker for any PC.
- Show statuses only: ready, acted, down, dead, stable.

3. Make initiative marker phase-aware.

`_get_combatant_marker()`:

- Suppress `[>] CURRENT TURN` for PCs when `pc_phase_complete` is true.
- Optionally mark enemy/NPC batch actors in ENEMY_PHASE if useful, but avoid adding another contradictory active pointer.

4. Remove legacy PC_PHASE enemy-before-PC processing.

`_determine_instruction_block()` currently has logic that can instruct processing NPCs before the active PC in PC_PHASE. This conflicts with the two-phase model.

Replace PC_PHASE behavior with:

- Current active PC only.
- No enemy/NPC processing until `/end` or initiative-driven ENEMY_PHASE.

5. Align prompt priority text.

In combat generation prompt:

- Change `[>] marker identifies active actor` to `[>] marker identifies active PC only during PC_PHASE`.
- State `CURRENT_PHASE` overrides all turn markers.
- State ENEMY_PHASE has no active PC, only a pending enemy/NPC batch.

6. Align validation prompt.

- During ENEMY_PHASE, prompting a PC with “what do you do” is invalid.
- During PC_PHASE, narrating enemy actions is invalid.
- The validator must not reject valid updateCharacterInfo actions where PCs are targets of enemy effects.

### Tests

Extend `scripts/test_multi_pc_combat.py`:

- `test_marker_no_current_turn_during_enemy_phase`
- `test_critical_override_suppressed_during_enemy_phase`
- `test_critical_override_present_during_pc_phase`
- `test_party_summary_no_active_pc_marker_during_enemy_phase`
- `test_pc_phase_instruction_block_has_no_enemy_processing`

Extend `scripts/c5_regression_combat.py`:

- Source gate: ENEMY_PHASE prompt does not include `CRITICAL OVERRIDE`.
- Source gate: combat prompt defines `[>]` as PC_PHASE-only.
- Runtime gate: opening `dmGroup` batch proceeds with enemy actors, not PC prompt.

### Acceptance Criteria

- ENEMY_PHASE prompt contains no active-PC command authority.
- PC_PHASE prompt contains no enemy batch processing instructions.
- GPT 5.4 Mini receives one clear phase authority surface.

## Phase 4: Deterministic Combat Command Replay Protection

### Goal

Prevent Python-applied `/att` and `/dmg` effects from being replayed as LLM mechanical updates.

### Files

- `core/managers/multi_pc_combat.py`
- `core/managers/combat_manager.py`
- `utils/combat_phase_integrity_precheck.py` or a new helper
- `updates/update_encounter.py`
- `prompts/combat/combat_sim_prompt_multipc_compressed.txt`
- `prompts/combat/combat_sim_prompt_multipc.txt`
- `prompts/combat/combat_validation_prompt_multipc_compressed.txt`
- `prompts/combat/combat_validation_prompt_multipc.txt`

### Implementation Tasks

1. Change deterministic command log format.

For `/dmg`:

```text
[ALREADY_APPLIED] Blairen dealt 10 damage (battleaxe) to Elite Bandit Bodyguard. Result HP: 8/18. [Bloodied]
```

For `/att` miss/hit confirmation:

- Use `[ALREADY_APPLIED]` when the mechanical hit/miss state is already resolved.
- Avoid wording that suggests the LLM should apply mechanics.

2. Add combat prompt directive.

Recommended compressed block:

```text
@DETERMINISTIC_COMMAND_RESULTS={
  already_applied: "Messages prefixed [ALREADY_APPLIED] report mechanics already committed by Python.",
  forbidden: "Do NOT emit updateEncounter or updateCharacterInfo ops for the same HP, hit, miss, ammo, or status result described in [ALREADY_APPLIED].",
  allowed: "Narrate cinematic consequences only, using current creature/PC state as truth."
}
```

3. Add validation guard.

If the current input/history contains `[ALREADY_APPLIED]` for a target and amount, reject same-response HP ops that duplicate the target/amount unless there is an explicit new damage source in the player input.

Start narrowly:

- Enemy target duplicate `updateEncounter.ops hp_delta == -amount`.
- Enemy target duplicate `set_hp` that equals current HP minus same amount or lower with no new damage source.

4. Keep replay detection for crash/resume separately.

Do not conflate this with existing resume replay suppression in `updates/update_encounter.py`. This is active-turn duplicate-damage prevention, not resume idempotency.

### Tests

Extend combat tests:

- `test_dmg_log_uses_already_applied_result_hp`
- `test_already_applied_prompt_contract_present`
- `test_duplicate_enemy_hp_delta_after_already_applied_rejected`
- `test_new_separate_damage_source_after_already_applied_allowed`
- `test_resume_replay_detection_still_passes_existing_cases`

### Acceptance Criteria

- `/dmg` can never cause duplicate LLM enemy HP mutation for the same deterministic damage event.
- Narration still describes the impact cinematically.
- Existing resume idempotency behavior is preserved.

## Phase 5: Combat Exit Post-Ops Simulation

### Goal

Allow valid enemy defeat plus `exit` in the same response while still blocking premature combat exits.

### Files

- `utils/combat_phase_integrity_precheck.py`
- `updates/update_encounter.py` for shared parsing/reference behavior if appropriate
- `scripts/test_combat_phase_integrity_precheck.py`
- `scripts/c5_regression_combat.py`

### Implementation Tasks

1. Add strict int parser.

Do not default malformed values to zero in a way that changes outcome.

Recommended:

```python
def _parse_int_strict(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
```

2. Add proposed encounter simulation.

Supported ops initially:

- `hp_delta`
- `set_hp`
- `set_status`
- optionally `condition_add` if defeated/unconscious conditions are represented there.

Rules:

- Match creature names using existing normalized name behavior where possible.
- If an op targets an unknown creature, skip it only if it is irrelevant to currently living hostile checks; otherwise return indeterminate.
- If HP parse fails for a relevant hostile update, return indeterminate.
- Statuses `dead`, `defeated`, `unconscious` count as resolved.
- HP `<= 0` counts as resolved even if status was not set, but downstream update logic should still normalize status.

3. Modify Guard 3.

Current:

- `exit` plus current living hostile -> reject.

New:

- `exit` plus current living hostile -> simulate supported same-response ops.
- If post-ops living hostiles remain -> reject.
- If post-ops no living hostiles -> pass.
- If simulation indeterminate -> reject with specific feedback.

4. Add correction feedback.

If blocked because simulation is indeterminate, feedback should tell the LLM to include supported `updateEncounter.ops` with exact creature names and HP/status updates before `exit`.

### Tests

Extend `scripts/test_combat_phase_integrity_precheck.py`:

- `test_exit_allowed_when_ops_eliminate_last_hostile`
- `test_exit_blocked_when_ops_leave_hostile_alive`
- `test_exit_blocked_when_no_update_encounter_present`
- `test_exit_allowed_with_multiple_hostiles_all_killed_by_ops`
- `test_exit_indeterminate_on_malformed_relevant_hp_op`
- `test_exit_indeterminate_on_unknown_relevant_creature_name`
- `test_exit_respects_status_defeated`

### Acceptance Criteria

- Correct final enemy defeat plus `exit` no longer loops validation.
- Premature `exit` remains blocked.
- Malformed or ambiguous defeat ops do not accidentally end combat.

## Phase 6: GPT 5.4 Mini Shim And Retry Audit

### Goal

Ensure narrator and combat calls use GPT-5-family chat params consistently and retry behavior increases reasoning where intended.

### Files

- `utils/ai_client_factory.py`
- `main.py`
- `core/managers/combat_manager.py`
- `model_config.py`
- Any direct `client.chat.completions.create(...)` call sites that still bypass `get_chat_completion_params()`.

### Current Observations

- `utils/ai_client_factory.py` has a GPT-5 parameter shim with `reasoning_effort` and `verbosity`.
- `get_chat_completion_params()` omits legacy `temperature` for GPT-5-family models unless explicitly enabled.
- Combat GPT-5 branch uses `retry_tier="high"` on retry.
- Some branches may not pass `timeout` in GPT-5 path where GPT-4.1 path does.
- Narrator retry paths should be audited to verify high-reasoning retry is actually applied after validation failure.

### Implementation Tasks

1. Inventory chat completion call sites.

For each call site, record:

- task_id
- model source
- whether `get_chat_completion_params()` is used
- timeout behavior
- retry tier behavior
- usage tracking behavior
- fallback behavior

2. Add source-contract tests for GPT-5 shim usage.

Tests should verify:

- GPT-5-family params include `reasoning_effort` and `verbosity`.
- GPT-5-family params do not include unsupported legacy `temperature` by default.
- Combat retry uses high reasoning.
- Narrator validation retry uses high reasoning or documented equivalent.
- Combat GPT-5 path includes timeout protection equivalent to GPT-4.1 path.

3. Normalize call sites.

- Replace direct model/temperature kwargs with `get_chat_completion_params()`.
- Add `timeout=...` where missing.
- Pass `retry_tier="high"` on retry paths that need increased reasoning.
- Keep fallback behavior fail-open or fail-closed according to existing domain contract.

### Tests

Recommended new file: `scripts/test_gpt54_chat_params_contract.py`.

Cases:

- `test_gpt54_params_include_reasoning_and_verbosity`
- `test_gpt54_params_exclude_temperature_by_default`
- `test_combat_retry_uses_high_reasoning`
- `test_narrator_retry_uses_high_reasoning`
- `test_combat_gpt5_path_has_timeout`
- `test_transition_narration_uses_factory_params`

### Acceptance Criteria

- GPT 5.4 Mini calls use valid shim params everywhere relevant.
- Retry behavior is deterministic and test-covered.
- No unsupported parameter is sent to GPT-5-family OpenAI chat completions.

## Phase 7: Prompt Audit And Simplification

### Goal

Reduce prompt contradiction and make compressed/uncompressed prompt pairs coherent.

### Files

- `prompts/system_prompt_compressed.txt`
- `prompts/system_prompt.txt`
- `prompts/validation/validation_prompt_compressed.txt`
- `prompts/validation/validation_prompt.txt`
- `prompts/combat/combat_sim_prompt_multipc_compressed.txt`
- `prompts/combat/combat_sim_prompt_multipc.txt`
- `prompts/combat/combat_validation_prompt_multipc_compressed.txt`
- `prompts/combat/combat_validation_prompt_multipc.txt`

### Audit Checklist

For narrator prompts:

- `updatePartyTracker` is cross-module/tracker flags only.
- `transitionLocation` is same-module movement only.
- `requestRoll` says stop and wait; no contingent outcome.
- `@FOLLOWER_STATE` reflects actual `scene_followers.json` mechanics.
- `@STATE_SYNC` remains concise and points to DM Note truth.
- NPC arrival rules include scene follower state support where appropriate.

For combat generation prompts:

- One phase authority model.
- No PC active-turn marker during ENEMY_PHASE.
- `[ALREADY_APPLIED]` directive present.
- `requestRoll` pause behavior is consistent with runtime support.
- Enemy updates and PC/NPC updates have strict routing boundaries.
- Exit rules mention same-response enemy defeat plus exit.

For combat validation prompts:

- Batch enemy phase with multiple `updateCharacterInfo` actions remains valid.
- More than one `updateEncounter` remains invalid.
- PC prompts during ENEMY_PHASE are invalid.
- Premature `exit` is invalid unless same-response ops resolve all hostiles.
- Duplicate `[ALREADY_APPLIED]` mechanics are invalid.

### Acceptance Criteria

- No compressed prompt has a rule contradicted by runtime-injected context.
- No generation prompt gives compatibility fallback equal weight to preferred strict behavior unless required.
- Compressed and uncompressed prompts agree on core contracts.

## Phase 8: Regression Harness And Gameplay Audit

### Goal

Create durable tests for the exact gametest failures so future model/prompt changes do not reintroduce them.

### Test Fixtures

Build deterministic fixtures for:

1. Thornwood NC02 -> NC05 location desync.
2. Captured Corrupted Ranger Thane following party through transitions.
3. Opening `dmGroup` enemy batch with PCs forbidden.
4. `/dmg` deterministic damage to enemy that should survive.
5. Final enemy killed by same-response `updateEncounter.ops` plus `exit`.
6. RequestRoll pause/resume once runtime support is hardened.

### Required Test Commands

Core syntax:

```bash
.venv/bin/python -m py_compile main.py core/ai/action_handler.py core/managers/combat_manager.py core/managers/multi_pc_combat.py utils/party_tracker_merge.py utils/combat_phase_integrity_precheck.py utils/multi_pc_dm_note.py utils/scene_follower_state.py
```

Targeted tests:

```bash
.venv/bin/python scripts/test_update_party_tracker_merge.py
.venv/bin/python scripts/test_scene_follower_transition_sync.py
.venv/bin/python scripts/test_multi_pc_combat.py
.venv/bin/python scripts/test_combat_phase_integrity_precheck.py
.venv/bin/python scripts/c5_regression_combat.py
.venv/bin/python scripts/test_gpt54_chat_params_contract.py
```

Existing non-regression tests to include where practical:

```bash
.venv/bin/python scripts/test_travel_state_sync_guard.py
.venv/bin/python scripts/test_npc_arrival_state_sync.py
.venv/bin/python scripts/test_narrator_location_exclusivity_guards.py
.venv/bin/python scripts/test_createencounter_failure_surfacing.py
.venv/bin/python scripts/test_update_encounter_ops_runtime.py
```

Optional UI smoke after backend stabilization:

```bash
# Use playwright-cli skill/workflow, not Playwright MCP.
```

## Implementation Order

Recommended order for minimum risk:

1. Phase 1: action normalization and tracker guard.
2. Phase 4: `/dmg` `[ALREADY_APPLIED]` replay protection.
3. Phase 3: combat phase prompt authority cleanup.
4. Phase 5: combat exit post-ops simulation.
5. Phase 2: scene follower sync and DM Note visibility.
6. Phase 6: GPT 5.4 Mini shim audit.
7. Phase 7: prompt simplification and parity sweep.
8. Phase 8: final regression harness and gametest smoke.

Rationale:

- Location desync and double damage directly corrupt mechanical state, so they go first.
- Combat prompt contradiction blocks combat flow and is next.
- Exit validation affects combat completion but is narrower.
- Scene followers affect narrative continuity and GUI visibility but are less likely to corrupt HP/position truth.
- GPT shim and prompt parity should be audited after runtime authority surfaces are clearer.

## Open Questions For Review

1. Should same-module `updatePartyTracker` location writes be rejected outright, or normalized to `transitionLocation` everywhere?

Recommendation: normalize before processing, reject at merge layer if normalization was bypassed.

2. Which scene follower dispositions definitely travel with the party?

Initial recommendation: `guarded_guide`, `following`, `captive`, `held`, `parleying`, `companion`, `escorted`.

3. Should `requestRoll` be fully implemented in this stabilization pass?

Recommendation: include minimal pending-roll persistence if combat prompts continue to prefer `requestRoll`. Otherwise reduce prompt preference until runtime support exists.

4. Should ENEMY_PHASE ever pause mid-batch for a PC saving throw?

Recommendation: yes eventually, but only after adding pending enemy-batch continuation state. Until then, allow single-save pause only if the batch continuation state is persisted.

5. Should GPT 5.4 Mini high reasoning be used on first attempt for combat ENEMY_PHASE only?

Recommendation: consider a targeted high-reasoning first attempt for ENEMY_PHASE batch and final-round exit responses if cost/latency is acceptable.

## Definition Of Done

This stabilization is complete when:

- Same-module location writes cannot corrupt `party_tracker.json` through `updatePartyTracker`.
- Traveling scene followers remain synchronized with party transitions and visible in DM Note.
- ENEMY_PHASE combat prompts contain no active-PC override instructions.
- `/dmg` deterministic damage cannot be applied twice by the LLM.
- Valid final enemy defeat plus `exit` passes precheck.
- Premature combat exit remains blocked.
- GPT 5.4 Mini chat parameter shim behavior is source-tested for narrator and combat paths.
- Compressed and uncompressed prompts agree on core narrator/combat contracts.
- Targeted regression tests cover all gametest failures described above.
