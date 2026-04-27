# tt-following-scene-entity-state

## Why

Some supernatural or scene-only entities begin as location-bound anchors but later need to follow, haunt, stalk, or accompany the party. Without a state model, the narrator either loses track of them after transition or violates location exclusivity by instantiating them away from their origin.

This change defines a future state model for following scene entities. It should remain separate from dead-PC stickiness and resurrection logic.

## What Changes

- Add explicit persistent state for scene entities that move with or follow the party.
- Location exclusivity guard MUST treat authorized followers as present at the party location.
- Location-bound anchors MUST remain protected unless explicitly promoted or moved.
- Scene followers MUST remain distinct from PCs and combat-valid monsters unless explicitly promoted to those roles.

## Non-Goals

- Do not implement PC resurrection.
- Do not make all scene anchors mobile by default.
- Do not weaken scene-entity combat validity rules.
- Do not require every dream, omen, or echo to become a scene follower.

## Capabilities

- New capability: `tt-following-scene-entity-state`

## Impact

Likely affected code:
- party tracker or a small adjacent scene-follower state file
- `utils/narrator_location_exclusivity_guard.py`
- `utils/scene_entity_contract.py`
- `main.py` or action handling for movement/promote operations
- focused tests under `scripts/`

Risks:
- Over-persisting subjective narration as entities. This is mitigated by requiring explicit state creation/movement.

Fallback:
- Keep entities location-bound and require foreshadowing-only narration outside origin location.
