## Context

`core/managers/multi_pc_combat.py` already contains the core deterministic model:

- `PCStatus.INCAPACITATED` represents a PC at 0 HP needing death saves.
- `PCCombatState.apply_death_save(roll)` applies natural 1, natural 20, success, failure, stabilization, and death outcomes.
- `CombatStateManager.get_incapacitated_pcs()` exposes PCs requiring death saves.
- `update_character_info(..., ops=...)` already supports deterministic `death_save_failure`, `death_save_success`, and `death_saves_set` ops.

The missing boundary is the combat input loop in `core/managers/combat_manager.py`. User roll input currently flows toward command handling or LLM generation instead of a deterministic death-save resolver.

## Contract Layer (MUST)

### Death-Save Gate Ownership

- Multi-PC combat runtime MUST detect when any PC-phase death-save obligation exists for a PC at 0 HP, not dead, and not stabilized.
- Death-save obligations MUST be evaluated at PC phase start, not as LLM-narrated individual initiative turns.
- When the PC-phase death-save gate is active, the runtime MUST emit a deterministic Python-authored Dungeon Master narration prompt naming the PC that needs a death saving throw.
- The death-save request prompt MUST be emitted through the normal visible/spoken `Dungeon Master:` output path and MUST be eligible for DM voice/TTS when enabled.
- The death-save request prompt MUST NOT include `[skipTTS]` or `[SYSTEM]` markers.
- While the gate is active, valid death-save roll input MUST be processed in Python before any LLM call.
- While the gate is active, invalid input MUST receive user-safe guidance and MUST NOT call the LLM.
- A PC MUST NOT be allowed to use `/att`, `/dmg`, or normal action commands while their required death save is unresolved.
- `/end` MUST be blocked while any unstable 0-HP PC has an unresolved death-save obligation for the current PC phase.

### Roll Parsing

- The resolver MUST accept roll values from at least these forms: `3`, `I roll 3`, `roll 3`, `/death 3`, and `/ds 3`.
- The resolver MUST interpret a bare integer `1..20` as a death-save roll only while the deterministic death-save gate is active.
- Outside an active death-save gate, bare numeric input MUST retain existing behavior and MUST NOT be hijacked as a death save.
- The resolver MUST reject missing, non-integer, and out-of-range values outside `1..20`.
- The resolver MUST treat the input as the natural d20 death-save result, not as a modified total.

### Mechanical Result Application

- Natural `1` MUST add two death-save failures.
- Rolls `2..9` MUST add one death-save failure.
- Rolls `10..19` MUST add one death-save success.
- Natural `20` MUST set HP to `1`, clear death saves, and return the PC to active/alive state.
- Three failures MUST mark the PC mechanically dead.
- Three successes MUST mark the PC stable in combat state and MUST persist schema-valid character state without writing `status: stable` to character JSON.
- Healing above `0 HP` MUST clear death-save counters and remove the death-save gate for that PC.

### Persistence

- Death-save results MUST be persisted immediately after deterministic application.
- Persistence MUST use existing deterministic character update surfaces where practical.
- Persisted character JSON MUST remain schema-valid: `status` SHALL be one of the schema enum values and `deathSaves` SHALL contain bounded `successes` and `failures` counters.
- If persistence fails, the runtime MUST surface a system error and MUST NOT silently continue as though the save was committed.

### Round Cadence

- A PC MUST be prompted at most once per PC phase for a death save unless the prior prompt was not resolved.
- After a death-save roll is resolved, that PC MUST be treated as having completed their PC-phase death-save obligation for that phase.
- On a later PC phase, the same PC MUST be prompted again if they remain at 0 HP with fewer than three successes and fewer than three failures.
- Stable or dead PCs MUST NOT be prompted for additional death saves.

### Compatibility

- Existing multi-PC command behavior for non-incapacitated PCs MUST remain unchanged.
- Enemy/NPC batch phase behavior MUST remain unchanged.
- Single-player combat behavior MUST remain unchanged unless a no-op shared helper is introduced.
- All new Python user-facing text MUST be ASCII-only.

## Guidance Layer (SHOULD)

### Helper Shape

Prefer adding small helpers to `MultiPCCombatManager` rather than embedding parsing and persistence deeply in the combat loop:

```python
def get_pending_death_save_pc(self) -> Optional[str]:
    """Return the next PC who must resolve a death save this PC phase."""

def parse_death_save_roll(self, user_input: str) -> Tuple[bool, Optional[int], str]:
    """Parse natural death-save roll input."""

def resolve_death_save_roll(self, pc_name: str, roll: int) -> Tuple[bool, str]:
    """Apply and persist one death-save roll."""
```

### Cadence Tracking

Prefer in-memory combat-manager metadata for per-round cadence, for example:

```python
death_save_resolved_phases: Dict[str, int]
```

This avoids adding persisted schema fields. The authoritative persisted state remains HP/status/deathSaves in the character JSON.

### Stable Persistence

Because `schemas/char_schema.json` does not allow `status: stable`, persist stable PCs as:

```json
{
  "hitPoints": 0,
  "status": "unconscious",
  "condition": "unconscious",
  "condition_affected": ["unconscious"],
  "deathSaves": {"successes": 3, "failures": 0}
}
```

In-memory combat state may keep `PCStatus.STABLE` to avoid repeated prompts.

### User Message Shape

Recommended DM-continuity death-save request text:

```text
Dungeon Master: Acheron falls still, breath shallow. Acheron needs to roll a death saving throw.
```

The exact displayed sentence may vary, but it MUST clearly name the PC and request a death saving throw through the normal Dungeon Master narration channel. Invalid input, blocked `/end`, and blocked action guidance SHOULD remain `[skipTTS] Dungeon Master: [SYSTEM] ...` because those are mechanical guardrails, not story narration.

### Edit Strategy

Apply one anchored patch at a time in large Python files. Run `.venv/bin/python -m py_compile` after each touched Python file before continuing.

## Rollback

- If natural-language parsing is unreliable, keep `/death` and `/ds` command handling only.
- If PC-phase cadence is too invasive, prompt whenever the active PC phase begins and at least one unstable 0-HP PC has not resolved the current pending gate.
- If structured ops persistence is insufficient for stable-state schema validity, add a narrow schema-valid persistence helper in `multi_pc_combat.py` and keep it covered by tests.
