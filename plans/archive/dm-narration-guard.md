# Narrator State Integrity Guards

**Status:** Archived and superseded by `plans/narrator-combat-stabilization.md`
**Priority:** Medium (State Integrity)
**Effort:** Small (~2 hours total)
**Created:** 2026-05-05

**Archive note:** This smaller plan is retained only for historical traceability.

Two independent desync patterns discovered during Thornwood Watch gameplay (2026-05-05). Both cause the authoritative mechanical state to diverge from the narrator's scene reality.

---

## Section 1: Location Desync (updatePartyTracker No-Module Guard)

### Problem

When the narrator LLM hallucinates an `updatePartyTracker` action with `currentLocationId` but without `module`, the action silently reverts the party's authoritative location in `party_tracker.json`. This causes state desync where narration describes one location but mechanical truth says another. The existing pre-processing guard in `main.py:8152-8184` only catches the case where both `currentLocationId` AND `module` are present -- the no-module case slips through.

### Observed Bug (Thornwood Watch, 2026-05-05)

1. Party correctly transitions from NC02 (Blighted Thornbriar Grove) to NC05 (The Corrupted Nexus) via `transitionLocation`
2. On next turn, AI narrates the Corrupted Nexus chamber (NC05) but emits:
   ```json
   {"action": "updatePartyTracker", "parameters": {
     "currentLocationId": "NC02",
     "currentLocation": "Blighted Thornbriar Grove",
     "currentAreaId": "NCW001",
     "currentArea": "Northern Corrupted Woods"
   }}
   ```
   Note: no `"module"` key.
3. Pre-processing guard skips (requires both `currentLocationId` + `module` to fire)
4. `_merge_party_tracker_updates` writes NC02 to `worldConditions`
5. `party_tracker.json` now says NC02, narration says NC05 -- DESYNC
6. Next 3 turns: DM Note feeds NC02 location, but AI's memory of Nexus narration persists. Mud.
7. Player calls it out; DM admits mistake

### Root Cause Trace

```
AI emits: updatePartyTracker{currentLocationId: "NC02"}  (no "module" key)
  -> main.py:8152: pre-processing requires BOTH has_location_id AND has_module
  -> GUARD SKIPS (no module key in params)
  -> _merge_party_tracker_updates writes NC02 to worldConditions
  -> party_tracker.json now says NC02, but narration/context say NC05
  -> DESYNC
```

## Prompt Contract

The system prompt (`prompts/system_prompt_compressed.txt`) already defines:
```
updatePartyTracker: update module/area/location fields; use for traveling to EXISTING modules.
```

`updatePartyTracker` is for **cross-module** travel. Same-module location changes should use `transitionLocation`. The AI violated this contract, and no Python guard caught it.

## Fix Plan: Two Defense Layers

### Layer A: Pre-Processing Guard Extension

**File:** `main.py`, lines 8150-8184

**Current logic:**
```python
if has_location_id and has_module:
    if target_module == current_module:
        # Convert to transitionLocation
```

**New logic** -- add an `elif` branch for the `has_location_id and not has_module` case:

```python
elif has_location_id and not has_module:
    # Same-module location-only change using wrong action type (no module param)
    new_location_id = params.get("currentLocationId", "")

    if new_location_id == current_location_id:
        # No-op: setting location to where we already are
        # Strip location keys from params, keep other fields
        # (e.g., resolvedHostilesByLocation updates should survive)
        for loc_key in ["currentLocationId", "currentLocation",
                        "currentAreaId", "currentArea"]:
            params.pop(loc_key, None)
        if not params:
            actions[i] = None  # filtered below
        else:
            actions[i]["parameters"] = params
        info("ACTION FIX: Stripped no-op location fields from "
             f"updatePartyTracker (already at {new_location_id})",
             category="action_preprocessing")
    else:
        # Location change within same module -- wrong action type
        actions[i] = {
            "action": "transitionLocation",
            "parameters": {"newLocation": new_location_id},
        }
        info("ACTION FIX: Converted updatePartyTracker to "
             f"transitionLocation({new_location_id}) (same module, no module key)",
             category="action_preprocessing")
    actions_modified = True

# After the loop, filter out None actions:
if actions_modified:
    actions = [a for a in actions if a is not None]
    response_data["actions"] = actions
```

### Layer B: Merge Guard (Defense-in-Depth)

**File:** `utils/party_tracker_merge.py`

**Change signature** to accept optional `current_module`:
```python
def _merge_party_tracker_updates(
    current_party_data: Dict[str, Any],
    parameters: Dict[str, Any],
    current_module: Optional[str] = None
) -> Dict[str, Any]:
```

**Add warning guard** in the location-key branch:
```python
if key in ["currentLocationId", "currentLocation",
           "currentAreaId", "currentArea"]:
    if key == "currentLocationId" and current_module is not None:
        new_module = parameters.get("module")
        old_id = (current_party_data.get("worldConditions", {})
                  .get("currentLocationId"))
        if (not new_module or new_module == current_module) \
           and old_id is not None \
           and value != old_id:
            warning(
                f"updatePartyTracker changing currentLocationId "
                f"{old_id} -> {value} within same module "
                f"'{current_module}' without module transition. "
                f"Should use transitionLocation instead.",
                category="party_management"
            )
    # ... existing write logic unchanged
```

**Update call site** in `core/ai/action_handler.py` (~line 3120):
```python
current_party_data = _merge_party_tracker_updates(
    current_party_data, parameters,
    current_module=current_module
)
```

**Update test** in `scripts/test_update_party_tracker_merge.py` to pass/accept the new parameter.

### Why Two Layers

| Scenario | Layer A (pre-processing) | Layer B (merge) |
|---|---|---|
| `updatePartyTracker{currentLocationId, module}` same-module | Converts to `transitionLocation` | Logs warning |
| `updatePartyTracker{currentLocationId}` no module, same location | Strips no-op location fields | Silent (no change) |
| `updatePartyTracker{currentLocationId}` no module, different location | Converts to `transitionLocation` | Logs warning |
| Future code path bypasses pre-processing | -- | Logs warning |
| `updatePartyTracker{module}` cross-module, no `currentLocationId` | Passes through | Passes through |

### Edge Cases (Not Affected)

- **`updatePartyTracker` with `resolvedHostilesByLocation` only**: No `currentLocationId`, guard doesn't fire. Normal pass-through.
- **`updatePartyTracker` with nested `worldConditions` update**: Only checks top-level `currentLocationId`. Nested location fields in `worldConditions` dict are not guarded (additive/non-breaking).
- **Cross-module travel with `module` but no `currentLocationId`**: Location auto-resolution in `process_action` handles finding the starting location. Not affected.
- **`moveBackgroundNPC`, `updateSceneFollower`, `updatePartyNPCs`**: Not `updatePartyTracker` action. Not affected.

## Test Coverage

New tests in `scripts/test_update_party_tracker_merge.py`:

| Test | What it covers |
|---|---|
| `test_upt_same_module_no_module_key_diff_location_converts` | Layer A: converts to `transitionLocation` when location differs |
| `test_upt_same_module_no_module_key_same_location_noop` | Layer A: strips location fields when already at target |
| `test_upt_merge_guard_warns_same_module_location_change` | Layer B: logs warning on same-module location change |
| `test_upt_cross_module_with_module_key_not_affected` | Non-regression: normal cross-module travel unaffected |
| `test_upt_resolved_hostiles_by_location_only_not_affected` | Non-regression: peaceful resolution marker passes through |

## Files Modified

| File | Change | Est. Lines |
|---|---|---|
| `main.py` | Add `elif` branch in pre-processing loop + `None` filter | ~30 |
| `utils/party_tracker_merge.py` | Add `current_module` param + log-warning guard | ~15 |
| `core/ai/action_handler.py` | Pass `current_module` kwarg to merge call | ~2 |
| `scripts/test_update_party_tracker_merge.py` | 5 new test functions | ~90 |

## Verification

```bash
# Syntax checks
python3 -m py_compile main.py utils/party_tracker_merge.py core/ai/action_handler.py

# Merge tests
python3 scripts/test_update_party_tracker_merge.py

# Existing regression suite
python3 scripts/test_party_member_autoregister_normalization.py
```

---

## Section 2: Scene Follower Location Sync on Transition

### Problem

When the party uses `transitionLocation` to move from one location to another within the same module, scene followers registered via `updateSceneFollower` remain at their old `current_location` in `data/runtime/scene_followers.json`. The narrator LLM correctly continues to narrate these followers as present (they're traveling with the party), but the mechanical state claims they're at the old location. This causes the GUI thumbnail strip to drop the follower and the validator to reject follower presence claims at the new location.

### Observed Bug (Thornwood Watch, 2026-05-05)

1. Party captures Corrupted Ranger Thane at NC02. AI emits:
   ```json
   {"action":"updateSceneFollower","parameters":{"entity":"Corrupted Ranger Thane","state":"present","entityType":"monster","disposition":"guarded_guide","currentLocation":"NC02","visibleInStrip":true,"monsterType":"Corrupted Ranger Thane"}}
   ```
2. `data/runtime/scene_followers.json` records: `"current_location": "NC02"`, `"lifecycle_state": "present"`
3. Party transitions: NC02 -> NC04 -> NC02 -> NC05
4. `party_tracker.json` updates correctly on each transition
5. `data/runtime/scene_followers.json` **never changes** -- Thane is still at NC02
6. AI narrates Thane as present at NC05 (correct narrative reality: he's bound to Chronos on a leash)
7. GUI thumbnail strip: Thane missing from NC05 monster thumbnail queue
8. Player notices: "did Corrupted Ranger Thane fall out of the scene follower list?"
9. AI confirms: "based on the current authoritative state, Ranger Thane is not on the active party/NPC list for NC05"

### Root Cause Trace

```
Party transitions NC02 -> NC05 via transitionLocation
  -> action_handler.py:2048 transitionLocation handler runs
  -> location_manager.handle_location_transition() updates party_tracker.json
  -> conversation_history appended with transition message
  -> NO code touches scene_followers.json
  -> data/runtime/scene_followers.json still says current_location: "NC02"

Later: narrator checks follower state
  -> main.py:2266 loads follower_store from scene_followers.json
  -> Finds Thane at NC02, party at NC05
  -> Validator rejects Thane presence at NC05 (or: GUI strip skips absent followers)

AI continues narrating Thane anyway (correctly -- narrative reality)
  -> but mechanical state says no
  -> DESYNC
```

### Code Audit

**`transitionLocation` handler** (`core/ai/action_handler.py:2048-2279`):
- Updates `party_tracker.json` via `location_manager.handle_location_transition` (line 2190)
- Appends transition message to conversation history (line 2210)
- Generates arrival narration (lines 2246-2279)
- **Zero references to `scene_follower_state` or `scene_followers.json`**

**`move_follower_to_location()`** (`utils/scene_follower_state.py:334-346`):
- Exists, tested, works correctly
- **Never called in production runtime code** -- only called in test files
- Imported in `action_handler.py:832` but only used in `update_scene_follower` handler, not in transition handler

**`@FOLLOWER_STATE` prompt directive** (`prompts/system_prompt_compressed.txt:194-199`):
```
correction: "To change a follower's location, use moveBackgroundNPC."
```
This guidance is **wrong**. `moveBackgroundNPC` manipulates area JSON NPC data, not `scene_followers.json`. The LLM has no way to update follower locations without emitting `updateSceneFollower`, and it may not know to do this after every transition.

### Fix Plan

**File:** `core/ai/action_handler.py`, in the `transitionLocation` handler (~line 2275, after arrival narration generation)

Add a sync step that iterates all scene followers and updates their `current_location`:

```python
# Sync scene followers to new location
try:
    from utils.scene_follower_state import (
        load_followers, get_follower_records,
        move_follower_to_location, save_followers
    )
    from utils.scene_follower_state import normalize_scene_follower_entity_id

    follower_store = load_followers()
    follower_records = get_follower_records(follower_store)

    synced_count = 0
    for follower in follower_records:
        if follower.get("lifecycle_state") == "present":
            entity_id = follower.get("entity_id")
            old_loc = follower.get("current_location")
            if old_loc != new_location_id:
                move_follower_to_location(
                    follower_store, entity_id, new_location_id
                )
                synced_count += 1

    if synced_count > 0:
        save_followers(follower_store)
        info(f"SCENE_FOLLOWER_SYNC: Moved {synced_count} follower(s) "
             f"to {new_location_id} during transition",
             category="scene_followers")
except Exception as e:
    warning(f"Scene follower sync failed during transition: {e}",
            category="scene_followers")
```

### Edge Cases

- **Empty follower store**: `load_followers()` returns `{"followers": []}`. Loop runs zero iterations. No-op.
- **Missing file**: `load_followers()` creates empty store. No-op.
- **Follower already at destination**: `old_loc == new_location_id` check skips. No unnecessary writes.
- **Removed followers**: `lifecycle_state` is not `"present"`. Skipped.
- **`new_location_id` unavailable**: Sync step placed after `new_location_id` is resolved (after topology validation, before arrival narration). Always defined.
- **Cross-module transition**: `transitionLocation` only works within same module. `updatePartyTracker` is for cross-module. Followers may or may not follow across modules. For now, only sync for `transitionLocation`. Cross-module follower behavior is a future concern.
- **Sync failure**: Fail-open. Exception logged, transition continues normally. Follower state stale but not corrupt.

### Why This Fixes the Bug

| Before | After |
|---|---|
| Thane at `NC02` in `scene_followers.json` | Thane sync'd to `NC05` on transition |
| Validator: Thane at NC02, party at NC05 = mismatch | Validator: Thane at NC05 = present, valid |
| GUI strip: Thane missing from NC05 thumbnails | GUI strip: Thane appears as NC05 monster/NPC |
| AI narration: says Thane present (but can't back it) | AI narration and mechanical truth aligned |
| AI forced to emit `updateSceneFollower` on every transition | Python handles it deterministically |

### Test Coverage

New tests in a new file `scripts/test_scene_follower_transition_sync.py`:

| Test | What it covers |
|---|---|
| `test_present_follower_moves_on_transition` | Follower with `lifecycle_state=present` syncs to new location |
| `test_non_present_follower_not_moved` | Removed/hidden followers stay at their current location |
| `test_multiple_followers_all_sync` | Multiple present followers all update |
| `test_follower_already_at_destination_noop` | Same-location transition doesn't change anything |
| `test_empty_follower_store_noop` | No followers, no crash |
| `test_missing_follower_file_noop` | File missing, no crash, transition completes |
| `test_sync_failure_fail_open` | Exception during save doesn't block transition |
| `test_sync_called_from_transition_handler` | Source contract: handler calls sync |

### Files Modified

| File | Change | Est. Lines |
|---|---|---|
| `core/ai/action_handler.py` | Add follower sync block in `transitionLocation` handler | ~25 |
| `scripts/test_scene_follower_transition_sync.py` | New test file, 8 test functions | ~150 |

### Verification

```bash
# Syntax checks
python3 -m py_compile core/ai/action_handler.py

# New tests
python3 scripts/test_scene_follower_transition_sync.py

# Existing follower tests (non-regression)
python3 scripts/test_narrator_location_exclusivity_guards.py
```

---

## Section 3: Combat Opening Enemy Batch Prompt Contradiction

### Problem

When the opening combat round starts with `dmGroup` (enemies win initiative), the combat prompt assembled in `combat_manager.py:4645-4663` injects TWO contradictory sets of instructions:

1. **`get_required_response_prompt()`** (correctly) says: `ENEMY_PHASE | FORBIDDEN: [all PCs] | DON'T NARRATE PCs`
2. **`format_party_turn_summary()` + `format_pc_context_for_prompt()`** (UNCONDITIONALLY) say: `[>] Blairen - CURRENT TURN` and `CRITICAL OVERRIDE: Only [Blairen] can act now`

The LLM sees both and often picks the CRITICAL OVERRIDE because it's louder (all-caps, exclamation marks). This causes the LLM to:
- Ignore opening enemy batch
- Ask "Blairen, what do you do?" instead of processing enemies
- Lock combat at Round 1 with enemies never acting

### Observed Bug (Thornwood Watch, 2026-05-05)

1. `createEncounter` fires: Blairen, Chronos, Lidda vs CR 12 enemies (initiative winner = dmGroup)
2. Python sets `openingEnemyBatchPending = True`, `pc_phase_complete = True`
3. Combat prompt generated with both blocks:
   ```
   CURRENT PHASE: ENEMY_PHASE | FORBIDDEN ACTORS: [Blairen, Chronos, Lidda]
   ...
   [>] Blairen (2) - CURRENT TURN
   ...
   !!! CRITICAL OVERRIDE: THE CURRENT ACTIVE PLAYER CHARACTER IS: [Blairen] !!!
   IGNORE all other turn indicators. Only [Blairen] can act now.
   ```
4. LLM: narrates enemy batch (correct, follows ENEMY_PHASE instruction)
   - But ALSO asks "[Blairen], what do you do?" (follows CRITICAL OVERRIDE)
   - Or: LLM skips enemy batch entirely, only asks Blairen
5. Combat locks; enemies never processed

### Root Cause Trace

```
Prompt assembly in combat_manager.py (lines 4645-4663):

multi_pc_context = f"""
=== INITIATIVE STATE ===
...
=== COMBAT PHASE STATE ===
CURRENT_PHASE: ENEMY_PHASE
PC_PHASE_COMPLETE: True
...

--- MULTI-PC COMBAT STATUS ---
{multi_pc_manager.format_party_turn_summary()}    <-- [>] Blairen - CURRENT TURN
{multi_pc_manager.format_pc_context_for_prompt(active_pc)}  <-- CRITICAL OVERRIDE: Only [Blairen]
"""
```

Both `format_party_turn_summary()` and `format_pc_context_for_prompt()` have ZERO awareness of the combat phase. They unconditionally mark the last active PC as "CURRENT TURN" and emit the CRITICAL OVERRIDE block.

Also, `format_initiative_tracker()` calls `_get_combatant_marker()` which marks any PC matching `current_pc_name` with `[>] CURRENT TURN` -- regardless of phase.

### Code Audit

**`format_pc_context_for_prompt()`** (`multi_pc_combat.py:1532-1558`):
- Always emits `!!! CRITICAL OVERRIDE: THE CURRENT ACTIVE PLAYER CHARACTER IS: [X] !!!`
- Always emits `IGNORE all other turn indicators. Only [X] can act now.`
- Has NO check for `pc_phase_complete` or `CURRENT_PHASE`

**`format_party_turn_summary()`** (`multi_pc_combat.py:1560-1587`):
- Marks `current_pc_name` with `[>]` marker
- Has NO check for `pc_phase_complete` or `CURRENT_PHASE`

**`_get_combatant_marker()`** (`multi_pc_combat.py:1698-1727`):
- For PC type: checks if `name == self._state.current_pc_name` -> returns `[>] CURRENT TURN`
- Has NO check for `pc_phase_complete`

**`format_initiative_tracker()`** (`multi_pc_combat.py:1807-1852`):
- Calls `_build_initiative_lines()` -> `_get_combatant_marker()` -> all PCs get `[>]` markers unconditionally
- The `_determine_instruction_block()` (line 1753) DOES correctly check `pc_phase_complete` and generates the ENEMY_PHASE "PROCESS TO END ROUND" block
- But the tracker lines and CRITICAL OVERRIDE appear LATER in the prompt (after the instruction block)

**Prompt assembly** (`combat_manager.py:4645-4694`):
- `multi_pc_context` block includes BOTH the correct phase info AND the contradictory CRITICAL OVERRIDE
- The CRITICAL OVERRIDE appears ~70 lines AFTER the REQUIRED RESPONSE, giving it recency bias

### Fix Plan

**File:** `core/managers/multi_pc_combat.py`

Three methods need phase-awareness:

#### Fix 1: `_get_combatant_marker()` -- suppress `[>]` during ENEMY_PHASE

```python
def _get_combatant_marker(self, combatant: Combatant) -> Tuple[str, str]:
    status = combatant.status.lower()
    name = combatant.name
    
    if TurnQueueManager._is_inactive_combatant(combatant) and combatant.type != CombatantType.PC:
        return "[D]", "Dead"
    if status == "dead":
        return "[D]", "Dead"
    
    if combatant.type == CombatantType.PC:
        pc_state = self._state.pc_states.get(name)
        if pc_state:
            if pc_state.status == PCStatus.ACTED:
                return "[X]", "Acted"
            # NEW: Don't mark any PC as current during enemy phase
            elif name == self._state.current_pc_name and not self._turns.pc_phase_complete:
                return "[>]", "CURRENT TURN"
        return "[ ]", "Waiting"
    
    return "[ ]", "Waiting"
```

#### Fix 2: `format_pc_context_for_prompt()` -- suppress CRITICAL OVERRIDE during ENEMY_PHASE

```python
def format_pc_context_for_prompt(self, pc_name: str) -> str:
    if pc_name not in self._state.pc_states:
        return ""
    
    # NEW: During enemy phase, suppress CRITICAL OVERRIDE block
    if self._turns.pc_phase_complete:
        return ""  # OR: return a phase-appropriate note
    
    state = self._state.pc_states[pc_name]
    lines = [
        f"!!! CRITICAL OVERRIDE: THE CURRENT ACTIVE PLAYER CHARACTER IS: [{pc_name}] !!!",
        f"IGNORE all other turn indicators. Only [{pc_name}] can act now.",
        f"HP: {state.current_hp}/{state.max_hp}",
        f"Status: {state.status.value}",
    ]
    # ... rest unchanged
```

#### Fix 3: `format_party_turn_summary()` -- modify `[>]` marker during ENEMY_PHASE

```python
def format_party_turn_summary(self) -> str:
    lines = [f"=== PC PARTY TURN STATUS (Round {self._state.current_round}) ==="]
    
    for name, state in self._state.pc_states.items():
        # NEW: No `[>]` marker during enemy phase
        if self._turns.pc_phase_complete:
            marker = "   "
        else:
            marker = "[>]" if name == self._state.current_pc_name else "   "
        # ... rest unchanged
```

### Test Coverage

| Test | What it covers |
|---|---|
| `test_marker_no_current_turn_during_enemy_phase` | `[>]` not emitted when `pc_phase_complete=True` |
| `test_critical_override_suppressed_during_enemy_phase` | `format_pc_context_for_prompt` returns empty in enemy phase |
| `test_critical_override_present_during_pc_phase` | Non-regression: CRITICAL OVERRIDE still emitted in PC_PHASE |
| `test_party_summary_no_pc_marks_during_enemy_phase` | No `[>]` markers in `format_party_turn_summary` during enemy phase |

### Files Modified

| File | Change | Est. Lines |
|---|---|---|
| `core/managers/multi_pc_combat.py` | Phase checks in 3 methods | ~10 |
| `scripts/test_multi_pc_combat.py` | 4 new test functions | ~60 |

### Verification

```bash
# Syntax checks
python3 -m py_compile core/managers/multi_pc_combat.py

# Multi-PC combat tests
python3 scripts/test_multi_pc_combat.py

# C5 regression suite
python3 scripts/c5_regression_combat.py
```

---

## Section 4: Combat Double-Damage from /dmg System Messages

### Problem

Every `/dmg` command applies damage deterministically in Python AND sends a system message to the LLM. The LLM interprets this message as an instruction to apply the same damage again via `updateEncounter` ops, causing **double damage**. This makes enemies die twice as fast and undermines the "Python enforces reality" principle.

### Observed Bug (Thornwood Watch, 2026-05-05)

```
Turn 1: Opening enemy batch (dmGroup wins initiative)
  Elite Bandit Bodyguard: 18/18, Corrupted Wolf: 13/13

Blairen /att 22 bodyguard battleaxe -> Hit!

Blairen /dmg 10
  Python: bodyguard HP 18-10=8, encounter file saved with HP 8
  System msg: "[System: blairen dealt 10 damage... HP: 8/18. [Bloodied]]"
  LLM narration: "Blairen's axe... bodyguard drops hard."
  LLM actions: updateEncounter{hp_delta:-10, set_hp:0, set_status:dead}
  Bodyguard: 18 -> 8 (Python) -> 0 (LLM duplicate). DEAD.

Chronos /att wolf 15 dagger -> Hit!

Chronos /dmg 7
  Python: wolf HP 13-7=6, encounter file saved with HP 6
  System msg: "[System: chronos dealt 7 damage... HP: 6/13. [Bloodied]]"
  LLM narration: "Chronos's knife... wolf yelps."
  LLM actions: updateEncounter{hp_delta:-7, set_hp:0, set_status:dead}
  Wolf: 13 -> 6 (Python) -> 0 (LLM duplicate). DEAD.
```

In two attacks, creatures that should have survived are dead. 18 extra damage dealt.

### Root Cause Trace

1. **`multi_pc_combat.py:1205`** -- Python applies damage: `target.hp -= amount` (18->8)
2. **`multi_pc_combat.py:1231`** -- Syncs to encounter_data in memory: `creature["currentHitPoints"] = 8`
3. **`multi_pc_combat.py:1236`** -- System message with **ambiguous** format:
   `"[System: blairen dealt 10 damage... HP: 8/18. [Bloodied]]"`
   The LLM reads "HP: 8/18" as PRE-damage state needing processing.
4. **`combat_manager.py:3972`** -- Injected as `role: "user"` into conversation_history
5. **`combat_manager.py:3980`** -- Encounter persisted to disk with updated HP
6. LLM generates: `updateEncounter{hp_delta:-10, set_hp:0}` -- applies 10 MORE damage
7. **`update_encounter.py:264`** -- Replay detection fails:
   - Regex extracts from "HP 8->0": expected HP = 0
   - Encounter has current HP = 8
   - `8 != 0` -> NOT a replay -> ops applied -> HP: 8 - 10 = 0. DEAD.

**Why replay detection doesn't catch this:** It was designed for combat resume (crashes), where the LLM re-emits `(HP 18->8)` matching already-applied state. Here the LLM proposes `(HP 8->0)` -- a NEW (wrong) transition. The detector correctly identifies it as new, but it's wrong.

### Fix (Two-Tier)

#### Primary: Change system message format

**File:** `core/managers/multi_pc_combat.py:1236`

Current:
```python
log_msg = f"[System: {actor_name} dealt {amount} damage ({flavor_text}) to {target.name}. HP: {target.hp}/{target.max_hp}.{status_update}]"
```

New:
```python
log_msg = f"[ALREADY_APPLIED] {actor_name} dealt {amount} damage ({flavor_text}) to {target.name}. Result HP: {target.hp}/{target.max_hp}.{status_update}"
```

Changes: `[System: ...]` -> `[ALREADY_APPLIED]` (unambiguous). `HP: ...` -> `Result HP: ...` (post-damage result).

#### Secondary: Update combat prompt contract

**File:** `prompts/combat/combat_sim_prompt_multipc_compressed.txt`

Add:
```
@DETERMINISTIC_DAMAGE_HANDLING =
  rule: "Messages with [ALREADY_APPLIED] prefix report damage ALREADY committed by Python. Creature HP in encounter state already reflects the result."
  forbidden: "Do NOT generate updateEncounter actions (hp_delta, set_hp) for damage in [ALREADY_APPLIED] messages."
  narration_only: "Narrate the hit cinematically. Mechanical state is correct."
```

Also apply same format to `/att` miss messages at line ~1144 for consistency.

**File:** `prompts/combat/combat_sim_prompt_multipc.txt` (uncompressed mirror -- same additions).

### Files Modified

| File | Change | Est. Lines |
|---|---|---|
| `core/managers/multi_pc_combat.py` | `/dmg` log_msg format + `/att` miss format | 2 |
| `prompts/combat/combat_sim_prompt_multipc_compressed.txt` | `@DETERMINISTIC_DAMAGE_HANDLING` directive | 6 |
| `prompts/combat/combat_sim_prompt_multipc.txt` | Same (mirror parity) | 6 |

### Verification

```bash
python3 -m py_compile core/managers/multi_pc_combat.py
python3 scripts/c5_regression_combat.py
python3 scripts/test_multi_pc_combat.py
```

---

## Section 5: Precheck Guard 3 Blind to Proposed Enemy State

### Problem

When the LLM processes the last living hostile during enemy phase and correctly includes both `updateEncounter` (kills the enemy) and `exit` in the same response, Guard 3 of `validate_combat_phase_integrity_precheck` rejects the response because it checks only the **current** `encounter_data` (from disk/file), not the **proposed** state after applying the `updateEncounter` ops.

This creates an unrecoverable retry loop: the LLM makes the correct response, the precheck rejects it, the LLM gets "VALIDATION FAILURE" feedback, retries with the same correct logic, and is rejected again.

### Observed Bug (Thornwood Watch, 2026-05-05)

```
Round 3, Enemy Phase. Malarok the Corruptor: 4/16 HP, alive.
Turn order: Dryad Sylara -> Scout Kira -> Malarok the Corruptor

LLM response (paraphrased):
  updateEncounter{ hp_delta:-6 (Malarok 4->0), set_hp:0, set_status:dead }
  exit{}

Precheck Guard 3:
  _has_exit_action(response_json) = True
  _encounter_has_living_hostiles(encounter_data) = True  (CURRENT state: Malarok 4/16, alive)
  -> REJECT: "exit action requested while living hostiles remain"

Retry log:
  Attempt 2/5: VALIDATION_FAIL -> retry with error feedback
  Attempt 3/5: VALIDATION_FAIL -> retry with error feedback
  Attempt 4/5: VALIDATION_FAIL -> retry with error feedback
  ...
```

Each retry injects `"VALIDATION FAILURE: Combat phase integrity precheck failed: exit action requested while living hostiles remain."` into conversation history. The LLM cannot fix the "error" because there is **no error in its response** — it correctly kills the last enemy during the enemy phase and calls exit. The precheck simply cannot see the proposed state.

### Root Cause Trace

```
combat_manager.py:1142-1146:
    validate_combat_phase_integrity_precheck(
        response_json,       # LLM's response with updateEncounter{hp_delta:-6, set_hp:0, status:dead} + exit
        encounter_data,      # CURRENT encounter state from file: Malarok 4/16, alive
        phase_state=...,
    )

combat_phase_integrity_precheck.py:169-175 (Guard 3):
    if _has_exit_action(response_json):                        # True
        has_living_hostiles = _encounter_has_living_hostiles(  # Checks encounter_data ONLY
            encounter_data
        )
        if has_living_hostiles is True:                        # True (current state)
            return False, "exit action requested while living hostiles remain."

combat_phase_integrity_precheck.py:94-121 (_encounter_has_living_hostiles):
    # Scans encounter_data["creatures"] for type=="enemy"
    # Checks currentHitPoints > 0 AND status not in ("dead","defeated","unconscious")
    # Returns True (Malarok: HP 4, status "alive")
    # NEVER inspects the proposed updateEncounter ops
```

Guard 3 was designed for the case where the LLM tries to exit while hostiles are definitively alive. It correctly catches hallucinated exits. But it was not designed for the case where `updateEncounter` ops in the **same response** would eliminate the living hostiles before the exit executes.

### Fix

**File:** `utils/combat_phase_integrity_precheck.py`

Add a simulation helper that builds a post-ops copy of encounter state, then modify Guard 3 to fall back to the simulated state.

#### New helper: `_encounter_has_living_hostiles_after_ops`

```python
def _encounter_has_living_hostiles_after_ops(
    encounter_data: Dict[str, Any],
    response_json: Dict[str, Any],
) -> Optional[bool]:
    """Simulate proposed updateEncounter ops, then check for living hostiles.

    Deep-copies encounter creature state, applies hp_delta / set_hp /
    set_status ops from any updateEncounter actions in the response,
    then re-evaluates living-hostile status against the post-simulation
    state.  Returns None (fail-open) when simulation cannot complete
    deterministically.
    """
    import copy

    creatures = encounter_data.get("creatures")
    if not isinstance(creatures, list):
        return None

    # Build simulation dict: name -> {type, hp, status}
    sim: Dict[str, Dict[str, Any]] = {}
    for c in creatures:
        name = c.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        sim[name] = {
            "type": str(c.get("type", "")).strip().lower(),
            "hp": _safe_int(c.get("currentHitPoints", c.get("hitPoints")), default=0),
            "status": str(c.get("status", "alive")).strip().lower(),
        }

    # Apply proposed updateEncounter ops
    actions = response_json.get("actions", [])
    if not isinstance(actions, list):
        actions = []

    for action in actions:
        if not isinstance(action, dict):
            continue
        if str(action.get("action", "")).strip().lower() != "updateencounter":
            continue
        params = action.get("parameters", {})
        if not isinstance(params, dict):
            continue
        ops = params.get("ops", [])
        if not isinstance(ops, list):
            continue
        for op in ops:
            if not isinstance(op, dict):
                continue
            creature_name = op.get("creature", "")
            if creature_name not in sim:
                continue
            op_type = str(op.get("op", "")).strip().lower()
            if op_type == "hp_delta":
                sim[creature_name]["hp"] += _safe_int(op.get("delta"), default=0)
            elif op_type == "set_hp":
                sim[creature_name]["hp"] = _safe_int(op.get("hp"), default=0)
            elif op_type == "set_status":
                new_status = str(op.get("status", "")).strip().lower()
                if new_status:
                    sim[creature_name]["status"] = new_status

    # Check post-simulation state for living hostiles
    has_enemy = False
    for state in sim.values():
        if state["type"] != "enemy":
            continue
        has_enemy = True
        if state["hp"] > 0 and state["status"] not in ("dead", "defeated", "unconscious"):
            return True

    if not has_enemy:
        return False
    return False


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce to int; return default on failure (never raise)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
```

#### Modified Guard 3

```python
# Guard 3: Illegal exit while hostiles remain.
if _has_exit_action(response_json):
    has_living_hostiles = _encounter_has_living_hostiles(encounter_data)
    if has_living_hostiles is True:
        # Fallback: simulate proposed updateEncounter ops and re-evaluate.
        # If ops in the same response would eliminate all hostiles, the
        # exit is legitimate.
        post_ops_living = _encounter_has_living_hostiles_after_ops(
            encounter_data, response_json
        )
        if post_ops_living is True:
            return False, (
                "Combat phase integrity precheck failed: "
                "exit action requested while living hostiles remain."
            )
        elif post_ops_living is None:
            # Simulation fail-open: let Guard 3's current-state result stand.
            return False, (
                "Combat phase integrity precheck failed: "
                "exit action requested while living hostiles remain "
                "(post-ops simulation indeterminate)."
            )
        # else: post_ops_living is False -> exit is legitimate, pass
```

### Why This Fixes the Bug

| Before | After |
|---|---|
| Precheck sees Malarok 4/16 (current state), rejects exit | Precheck simulates Sylara's ops: Malarok HP 4->0, status=dead |
| Retry loop: LLM keeps making correct response, precheck keeps rejecting | Precheck sees post-simulation state: no living hostiles -> pass |
| Combat gets stuck | Combat exits normally, returns to exploration mode |

### Edge Cases

- **No updateEncounter in response**: `_encounter_has_living_hostiles_after_ops` simulates zero ops, returns same result as `_encounter_has_living_hostiles`. Guard 3 rejects. Correct.
- **Partial kill (one enemy killed, another still alive)**: Post-ops simulation shows remaining living hostile. Returns `True`. Guard 3 rejects. Correct.
- **Malformed ops (missing hp value)**: `_safe_int` returns 0. Simulation may produce incorrect result, but this is safe — if simulation incorrectly shows no hostiles, exit passes (acceptable false positive). If simulation shows remaining hostiles, Guard 3 rejects (correct).
- **Ambiguous creature name (op targets "Malarok" but encounter has "Malarok the Corruptor")**: Creature not found in sim dict. Op skipped. Simulation may miss a kill. Guard 3 may reject. Sub-optimal but safe — prevents false exit.
- **Empty encounter_data**: `_encounter_has_living_hostiles` returns `None`. `has_living_hostiles is True` is `False`. Guard 3 does not fire. Same behavior as today. Safe.
- **Non-list ops**: `continue`-ed. No simulation. Guard 3 uses current-state check. Same behavior as today. Safe.

### Test Coverage

New tests in `scripts/test_combat_phase_integrity_precheck.py`:

| Test | What it covers |
|---|---|
| `test_exit_allowed_when_ops_eliminate_last_hostile` | `updateEncounter{set_hp:0, status:dead} + exit` passes when last enemy killed by ops |
| `test_exit_blocked_when_ops_leave_hostile_alive` | `updateEncounter{hp_delta:-2} + exit` blocked when enemy still alive post-ops |
| `test_exit_blocked_when_no_updateEncounter_present` | Only `exit` action, no ops to simulate, still blocked |
| `test_exit_allowed_with_mixed_ops_killing_multiple` | Multiple enemies killed by ops in same response, exit passes |
| `test_post_ops_simulation_respects_status_defeated` | Enemy set to `status=defeated` by ops counts as eliminated |
| `test_post_ops_simulation_fail_open_on_malformed_ops` | Missing hp/creature values handled gracefully without crash |

### Files Modified

| File | Change | Est. Lines |
|---|---|---|
| `utils/combat_phase_integrity_precheck.py` | Add `_safe_int`, `_encounter_has_living_hostiles_after_ops`, modify Guard 3 | ~60 |
| `scripts/test_combat_phase_integrity_precheck.py` | 6 new test functions | ~80 |

### Verification

```bash
# Syntax check
python3 -m py_compile utils/combat_phase_integrity_precheck.py

# Precheck tests
python3 scripts/test_combat_phase_integrity_precheck.py

# Combat regression suite
python3 scripts/c5_regression_combat.py
```

---

## Section 6: Scene Follower DM Note Visibility Gap

### Problem

Scene followers (entities with `entity_type: "monster"` captured/befriended via `updateSceneFollower`) are correctly persisted to `data/runtime/scene_followers.json`, correctly shown in the GUI thumbnail strip, and correctly recognized by the narrator location exclusivity guard. But the LLM cannot see them in its DM Note context because the "PARTY NPCs" section is built ONLY from `party_tracker.json`'s `partyNPCs` list, which does not include monster-type scene followers.

### Observed Bug (Thornwood Watch, 2026-05-05)

```
DM Note block fed to LLM:

--- PARTY NPCs (DM CONTROLLED) ---
Scout Kira (Lv? Rogue); Dryad Sylara (Lv? None)

--- FOLLOWER STATE ---
@FOLLOWER_STATE=
  present_scene: "Followers are valid present-scene claims at their tracked currentLocation."

scene_followers.json:
  Corrupted Ranger Thane: current_location=NC05, lifecycle_state=present,
                          entity_type=monster, visible_in_strip=true

Player: "Since Thane is with us, can I make an insight check on him?"

LLM response: "Based on the current authoritative state, Ranger Thane is not
on the active party/NPC list for NC05."
```

The LLM sees the `@FOLLOWER_STATE` directive saying followers are valid, but has ZERO data about which followers exist or where they are. It also doesn't see Thane in the PARTY NPCs list. So it defaults to "not present."

### Root Cause Trace

```
build_multi_pc_dm_note() at utils/multi_pc_dm_note.py:523-526:
  party_npcs = packet_party.get("party_npcs", [])     # From party_tracker.json only
  party_npcs_str = format_party_npcs(party_npcs)        # -> "Scout Kira ...; Dryad Sylara ..."

  # NO code looks at data/runtime/scene_followers.json
  # NO code checks for lifecycle_state=="present" at effective_location_id

main.py:2266-2279:
  follower_store = load_followers()
  follower_records = built for narrator_exclusivity_guard
  # follower_records is passed to evaluate_location_exclusivity_decision()
  # but NOT passed to build_multi_pc_dm_note()
```

The DM Note builder has zero awareness of scene followers. The exclusivity guard has follower data but never shares it.

### Fix

**File:** `utils/multi_pc_dm_note.py`

After building `party_npcs_str` from party tracker data (line 526), load present scene followers at the current location and append their display names.

```python
# After line 526: party_npcs_str = format_party_npcs(party_npcs)

# --- New block: Append present scene followers at current location ---
scene_follower_entries = []
try:
    from utils.scene_follower_state import get_follower_records, load_followers
    follower_store = load_followers()
    follower_list = get_follower_records(follower_store)
    if follower_list:
        current_loc = effective_location_id.upper() if effective_location_id else ""
        for r in follower_list:
            if r.get("lifecycle_state") != "present":
                continue
            if str(r.get("current_location", "")).strip().upper() != current_loc:
                continue
            entity_id = str(r.get("entity_id", "")).strip()
            entity_type = str(r.get("entity_type", "")).strip() or "unknown"
            disposition = str(r.get("disposition", "")).strip() or "accompanying"
            if entity_id:
                scene_follower_entries.append(
                    f"{entity_id} ({entity_type}, {disposition})"
                )
except Exception:
    # Fail-open: scene_follower_state not importable or file missing.
    pass

if scene_follower_entries:
    follower_str = "; ".join(scene_follower_entries)
    if party_npcs_str == "None":
        party_npcs_str = follower_str
    else:
        party_npcs_str = party_npcs_str + "; " + follower_str
```

**Result:**

| Before | After |
|---|---|
| `PARTY NPCs: Scout Kira (Lv? Rogue); Dryad Sylara (Lv? None)` | `PARTY NPCs: Scout Kira (Lv? Rogue); Dryad Sylara (Lv? None); Corrupted Ranger Thane (monster, guarded_guide)` |
| LLM: "Thane is not on active NPC list" | LLM: sees Thane, processes insight check normally |
| LLM has `@FOLLOWER_STATE` directive but no data | LLM has directive AND data to verify against |

### Edge Cases

- **Empty follower store**: `follower_list` is `[]`. Loop runs zero iterations. No-op.
- **Missing `scene_followers.json`**: `load_followers()` creates empty store. No-op.
- **Import failure**: `try/except` catches. No-op. Existing behavior preserved.
- **Follower at different location** (after section 5 sync fix): `current_location != effective_location_id`. Filtered out. Correct.
- **`lifecycle_state: "removed"`**: Filtered out. Correct.
- **Multiple followers at location**: All appended with `"; "` separator.
- **`party_npcs_str == "None"` and followers exist**: Replaces "None" with follower string (no trailing "None" label).

### Files Modified

| File | Change | Est. Lines |
|---|---|---|
| `utils/multi_pc_dm_note.py` | Add scene follower lookup after `party_npcs_str` construction (line 526) | ~22 |

### Verification

```bash
# Syntax check
python3 -m py_compile utils/multi_pc_dm_note.py

# DM note tests
python3 scripts/test_multi_pc_dm_note.py

# Scene follower tests (non-regression)
python3 scripts/test_scene_follower_transition_sync.py
```
