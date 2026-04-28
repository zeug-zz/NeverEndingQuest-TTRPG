# tt-dead-pc-mechanical-stickiness

## Why

Dead PCs must remain mechanically dead until an explicit resurrection or corruption transition changes that state. The Vitreol incident showed that ordinary rest and character-state hygiene can silently convert `status: dead` plus three failed death saves into an alive, fully rested PC, while the narrator lacks strong DM Note visibility into death state.

This change preserves the prime directive from `plans/narration-reality.md`: Python enforces reality; the DM interprets it.

## What Changes

- Dead PC state MUST be sticky when `status == "dead"` or `deathSaves.failures >= 3`.
- Generic positive HP writes, repairs, loads, healing text, and ordinary rest MUST NOT clear dead status or reset death-save failures.
- Ordinary long and short rest processing MUST skip dead characters without mutating HP, slots, features, exhaustion, or death saves.
- DM Note PC stat blocks MUST expose explicit status and death-save truth when a PC is dead or dying.
- Existing stale-unconscious cleanup for living positive-HP characters SHOULD remain intact.

## Non-Goals

- Do not implement a resurrection action in this change.
- Do not decide Vitreol's canon repair state.
- Do not remove supernatural narration, dreams, visions, corruption, or possession.
- Do not weaken Python authority over HP/status/death saves.

## Capabilities

- New capability: `tt-dead-pc-mechanical-authority`
- New capability: `tt-rest-dead-character-skip`
- New capability: `tt-dm-note-death-visibility`

## Impact

Affected code:
- `utils/character_state_hygiene.py`
- `updates/update_character_info.py`
- `core/ai/action_handler.py`
- `utils/multi_pc_dm_note.py`
- focused regression tests under `scripts/`

Risks:
- A previously corrupted live character file with `status: dead` and positive HP will now normalize back to dead/0 HP.
- Existing tests that assumed positive HP always clears status must be updated to distinguish stale unconscious from explicit death.

Fallback:
- If dead-stickiness introduces regressions, disable only the new dead predicate path while preserving rest and DM Note test coverage for further diagnosis.
