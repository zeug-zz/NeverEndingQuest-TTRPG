## Why

Recent multi-PC combat gametesting exposed three combat-stability failures that share one root cause: Python mechanical authority and LLM prompt authority are not cleanly separated during phase transitions and fast-lane command handoff.

First, ENEMY_PHASE prompts can still contain active-PC override language such as `Only [PC] can act now` or `[>] CURRENT TURN` markers. GPT 5.4 Mini can follow that contradictory late-context signal instead of resolving the enemy batch.

Second, deterministic `/dmg` and `/att` command results are written into combat history as human-readable messages that look like fresh combat events. GPT 5.4 Mini may emit `updateEncounter` or `updateCharacterInfo` ops for the same already-applied mechanical result, causing duplicate damage.

Third, combat phase-integrity guards reject `exit` while the current encounter still contains living hostiles, even when the same response includes supported `updateEncounter.ops` that defeat the final hostile before exiting. This creates validation loops at legitimate combat completion.

## What Changes

- **Phase-aware combat prompt context**: Suppress active-PC markers and critical override blocks during ENEMY_PHASE.
- **PC_PHASE cleanup**: Remove legacy prompt paths that instruct enemy/NPC processing during PC_PHASE.
- **Deterministic command result markers**: Prefix Python-applied fast-lane command results with `[ALREADY_APPLIED]` and use unambiguous `Result HP` wording.
- **Replay protection**: Add prompt and validation guards that prohibit duplicate mechanical ops for `[ALREADY_APPLIED]` results.
- **Combat exit post-ops simulation**: Simulate supported same-response enemy ops before deciding whether `exit` is premature.

## Capabilities

### New Capabilities

- `tt-combat-phase-authority-cleanup`: Combat prompt context presents one phase authority model with no active-PC override during ENEMY_PHASE.
- `tt-combat-deterministic-command-replay-guard`: Already-applied deterministic combat command results cannot be re-applied by LLM ops.
- `tt-combat-exit-post-ops-resolution`: Phase-integrity guards evaluate supported same-response enemy defeat ops before rejecting combat exit.

### Modified Capabilities

- `tt-combat-phase-integrity-guards`: Exit guard accounts for proposed supported encounter ops.
- `tt-combat-runtime-prompt-authority`: Runtime-injected combat context no longer contradicts phase state.
- `tt-combat-structured-encounter-ops-routing`: Enemy ops remain the supported mutation surface for enemy defeat before exit.

## Non-Goals

- Do not redesign initiative or the two-group phase model.
- Do not change PC/allied vs enemy mutation routing boundaries.
- Do not implement full pending-roll continuation state in this change.
- Do not make validation probabilistic when deterministic phase state is clear.
- Do not remove existing resume replay guards.

## Impact

- **Affected code**: `core/managers/multi_pc_combat.py`, `core/managers/combat_manager.py`, `utils/combat_phase_integrity_precheck.py`, combat prompts, and combat regression tests.
- **Runtime behavior**: ENEMY_PHASE should reliably resolve enemy/NPC batches; deterministic `/dmg` should no longer duplicate damage; valid final defeat plus `exit` should pass.
- **Backward compatible**: Existing command syntax remains unchanged. Existing structured enemy ops remain supported.
- **SP/MP compatibility**: Changes focus on multi-PC combat prompt/runtime paths; deterministic exit guard behavior remains conservative.
- **Rollout risk**: Medium-high. Combat prompt context and validation guards are high-value runtime paths. Mitigation is source-contract plus behavior regression tests.

## Fallback Strategy

If phase-context cleanup causes missing active-PC prompts, revert only PC_PHASE context formatting while preserving ENEMY_PHASE suppression. If exit simulation is too broad, narrow supported ops to `hp_delta`, `set_hp`, and `set_status` only. If replay guard is overbroad, limit it to same target and same amount duplicate enemy HP ops from immediate `[ALREADY_APPLIED]` context.
