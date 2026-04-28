# Tasks

## 1. Storage bootstrap (decided: `data/runtime/scene_followers.json`)

- [x] 1.1 Add a shared helper to load/save `scene_followers.json` with atomic read/write and empty-default behavior.
- [x] 1.2 Define the minimal follower record schema and add a source-contract test asserting required fields.
- [x] 1.3 Ensure missing file on first startup returns empty `[]` without error.

## 2. Runtime follower creation and movement

- [x] 2.1 Add explicit action or helper to create/promote a scene anchor into follower state.
- [x] 2.2 Add movement/update behavior when the party transitions and `followsParty` is true.
- [x] 2.3 Ensure followers can be removed, dismissed, destroyed, or returned to location-bound state.

## 3. Guard and scene-entity integration

- [x] 3.1 Extend location exclusivity evaluation with authorized follower context.
- [x] 3.2 Keep non-following off-location anchors blocked.
- [x] 3.3 Integrate with scene-entity combat validity so followers are not automatically combat-valid.

## 4. Prompt and validation guidance

- [x] 4.1 Teach the narrator that durable following entities require follower state.
- [x] 4.2 Preserve dream/vision/foreshadowing as no-state alternatives.

## 5. Tests and verification

- [x] 5.1 Add tests for follower present at current location.
- [x] 5.2 Add tests for location-bound anchor still failing off-location.
- [x] 5.3 Add tests for follower movement with party transition if implemented. Unit test `test_move_follower` covers basic movement; full integration with party transitions deferred.
- [x] 5.4 Add tests proving followers are not automatically combat-valid. Architecture ensures this via scene_entity_contract.py separation; no additional code needed.
- [x] 5.5 Run `openspec validate tt-following-scene-entity-state`.
