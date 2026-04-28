# Design: Dead PC Mechanical Stickiness

## Problem Boundary

Mechanical death is objective state. Narration may interpret death, corruption, soul echoes, dreams, or false returns, but ordinary runtime maintenance must not turn death into life.

## Core Rule

A character is mechanically dead if either condition is true:

- `status` canonicalizes to `dead`
- `deathSaves.failures >= 3`

When mechanically dead, normalization MUST enforce:

- `status = "dead"`
- `hitPoints = 0`
- `deathSaves.failures >= 3`
- `condition = "none"`
- no `unconscious` condition marker

The only future exception is an explicit resurrection/corruption state action. That exception is intentionally deferred to `tt-resurrection-and-corruption-state-action`.

## Implementation Strategy

1. Add a small helper in `utils/character_state_hygiene.py`, such as `is_mechanically_dead(character_data)`, and use it inside `normalize_life_state_fields()` before the positive-HP alive branch.
2. Mirror the same authority in `updates/update_character_info.py::_sync_death_save_state()` so deterministic ops and prose fallback updates cannot revive dead PCs by setting HP positive.
3. Add a rest guard in `core/ai/action_handler.py::_process_character_rest()` immediately after loading character data and before building restoration actions.
4. Add explicit status/death-save visibility in `utils/multi_pc_dm_note.py` for full and condensed PC stats.
5. Add focused regressions.

## Compatibility

Living positive-HP characters with stale `unconscious` status SHOULD still normalize to `alive`. The new dead path applies only to explicit death or three failed death saves.

## Rollback

The helper can be isolated behind one predicate. If needed, revert the predicate usage without altering unrelated rest or DM Note formatting code.
