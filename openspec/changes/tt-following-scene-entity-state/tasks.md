# Tasks

## 1. State model decision

- [ ] 1.1 Inspect existing party tracker, background NPC, and scene-entity storage patterns.
- [ ] 1.2 Choose storage for following scene entities.
- [ ] 1.3 Define the minimal follower record schema and migration/default behavior.

## 2. Runtime follower creation and movement

- [ ] 2.1 Add explicit action or helper to create/promote a scene anchor into follower state.
- [ ] 2.2 Add movement/update behavior when the party transitions and `followsParty` is true.
- [ ] 2.3 Ensure followers can be removed, dismissed, destroyed, or returned to location-bound state.

## 3. Guard and scene-entity integration

- [ ] 3.1 Extend location exclusivity evaluation with authorized follower context.
- [ ] 3.2 Keep non-following off-location anchors blocked.
- [ ] 3.3 Integrate with scene-entity combat validity so followers are not automatically combat-valid.

## 4. Prompt and validation guidance

- [ ] 4.1 Teach the narrator that durable following entities require follower state.
- [ ] 4.2 Preserve dream/vision/foreshadowing as no-state alternatives.

## 5. Tests and verification

- [ ] 5.1 Add tests for follower present at current location.
- [ ] 5.2 Add tests for location-bound anchor still failing off-location.
- [ ] 5.3 Add tests for follower movement with party transition if implemented.
- [ ] 5.4 Add tests proving followers are not automatically combat-valid.
- [ ] 5.5 Run `openspec validate tt-following-scene-entity-state`.
