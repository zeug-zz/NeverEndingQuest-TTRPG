## Context

The current deterministic command path already parses `/att` and `/dmg` in `MultiPCCombatManager.handle_combat_command(...)`. `/att` hit is already fast because Python compares attack roll to AC and prompts for `/dmg` without LLM. `/att` miss and `/dmg` currently produce already-applied command messages that can continue into the combat LLM path for narration and validation.

This change makes supported deterministic outcomes terminal inside the PC command path by returning enough structured information for `combat_manager.py` to print both a mechanical report and a short spoken narration, then continue the input loop.

## Contract Layer (MUST)

### Deterministic PC Command Fast Path

- Multi-PC PC_PHASE `/att` misses MUST be resolvable without calling the combat LLM when fast-path narration is enabled.
- Multi-PC PC_PHASE `/dmg` results MUST be resolvable without calling the combat LLM when fast-path narration is enabled.
- `/att` hit-pending-damage behavior MUST remain immediate and no-LLM.
- The fast path MUST preserve existing command syntax.
- The fast path MUST remain disableable through a config flag.

### Mechanical Report And Spoken Narration Split

- Mechanical reports MUST include `[skipTTS]`.
- Spoken deterministic narration MUST NOT include `[skipTTS]`.
- Mechanical reports MUST include enough state facts for facilitator trust, such as roll vs AC or HP before/after.
- Spoken narration MUST be derived only from committed mechanical facts.

### State Persistence

- `/dmg` fast path MUST persist enemy HP/status changes exactly as the current path does.
- `/dmg` fast path MUST queue/sync PC or allied NPC damage updates when the damaged target is not an enemy.
- Fast-path output MUST NOT cause duplicate `updateEncounter` or `updateCharacterInfo` mechanics.

## Guidance Layer (SHOULD)

### Command Result Structure

Prefer replacing tuple return values with a small structured result object or dictionary:

```python
{
    "handled": True,
    "mechanical_feedback": "[skipTTS] Dungeon Master: ...",
    "spoken_narration": "Dungeon Master: ...",
    "history_log": None,
    "requires_llm": False,
    "event": {...}
}
```

If minimizing code churn is more important, retain the tuple but add a third return value for deterministic narration. The implementation must keep call-site behavior clear and tested.

### Narration Templates

Use short ASCII-only templates. Select variants deterministically from event fields rather than global randomness so tests remain stable.

Template families should cover:

- attack miss
- nonlethal wound
- bloodied/severely wounded target
- defeat/death

### Feature Flag

Add a config constant such as:

```python
COMBAT_FAST_DETERMINISTIC_NARRATION = True
```

The flag should default to `True` only after tests pass and manual smoke is acceptable. During first implementation review, default may be discussed.

## Rollback

- Disable the config flag to restore current LLM narration flow for `/att` miss and `/dmg`.
- If structured command result refactoring causes regressions, revert to tuple extension and preserve helper functions.
