# Design: Scene Follower Thumbnail State

## Architecture Boundary
The durable source of truth remains `data/runtime/scene_followers.json`, managed by `utils/scene_follower_state.py`. The LLM may request follower changes through a structured action, but Python validates and commits all state.

Existing minimal records remain valid:

```json
{
  "entity_id": "corrupted_ranger_thane",
  "current_location": "NC02",
  "since_turn": "2026-04-30T12:00:00Z"
}
```

This change adds optional metadata only:

```json
{
  "entity_id": "corrupted_ranger_thane",
  "current_location": "NC02",
  "since_turn": "2026-04-30T12:00:00Z",
  "display_name": "Corrupted Ranger Thane",
  "entity_type": "monster",
  "monster_type": "Corrupted Ranger Thane",
  "disposition": "guarded_guide",
  "visible_in_strip": true,
  "source_module": "The_Thornwood_Watch",
  "source_entity_slug": "corrupted_ranger_thane"
}
```

## Structured Action
Introduce `updateSceneFollower` or an equivalent action handler contract.

Example:

```json
{
  "action": "updateSceneFollower",
  "parameters": {
    "entity": "Corrupted Ranger Thane",
    "entityType": "monster",
    "state": "following",
    "disposition": "guarded_guide",
    "currentLocation": "NC02",
    "visibleInStrip": true
  }
}
```

The handler MUST validate before writing. The handler SHOULD normalize camelCase action parameters into snake_case persisted fields, matching current repository JSON style where practical.

## Validation Sources
An update is valid only when the entity is grounded by at least one authoritative source:
- module monster file or bestiary entry;
- module NPC/current-location NPC authority;
- existing scene follower record;
- explicit scene authority metadata;
- recent validated encounter outcome available to deterministic runtime state;
- validated plot/location update processed in the same turn.

Invalid updates fail closed for state mutation but should surface a safe player/operator message rather than silently creating an ungrounded actor.

## Lifecycle States
Supported lifecycle states are intentionally narrow:
- `following`
- `present`
- `held`
- `parleying`
- `hidden`
- `released`
- `escaped`
- `dead`
- `joined_party`
- `combat_started`

`following`, `present`, `held`, and `parleying` may keep a record visible when `visible_in_strip` is true. `hidden`, `released`, `escaped`, `dead`, `joined_party`, and `combat_started` MUST remove or hide the follower from the non-combat thumbnail lane unless another authoritative state says otherwise.

## Thumbnail Payload Integration
`web/extensions/tabletop_socket_handlers.py` should merge visible current-location follower records into the existing `location_hostiles` lane outside combat when the follower is monster-like or hostile-scene-like.

Rules:
- Only include records whose `current_location` matches `party_tracker.worldConditions.currentLocationId`.
- Only include records with `visible_in_strip` true, or equivalent explicit visibility state.
- Route monster-like records through monster media metadata (`media_type="monster"`).
- Dedupe against party members, party NPCs, current-location NPCs, and explicit visible hostiles.
- Do not read generic `location.monsters` for this purpose.

## Observability
Follower update commits SHOULD log entity id, state, current location, visibility, and validation source. Invalid updates SHOULD log a structured reason such as `unresolved_entity`, `invalid_location`, `invalid_disposition`, or `combat_state_conflict`.

## Backward Compatibility
Existing `scene_followers.json` records with only `entity_id`, `current_location`, and `since_turn` MUST remain valid. They may be ignored by thumbnail emission until visibility/media metadata is present.

## Rollback
Rollback can disable `updateSceneFollower` handling and follower-to-thumbnail merging while leaving existing follower records intact for narrator location exclusivity.
