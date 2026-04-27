# Design: Following Scene Entity State

## State Model

The minimal follower record SHOULD include:

```json
{
  "anchorId": "vitreol_thrall",
  "displayName": "Corrupted Vitreol",
  "originLocationId": "NC02",
  "currentLocationId": "NC04",
  "followsParty": true,
  "entityType": "scene_entity",
  "combatValid": false,
  "source": "Voidstone altar ritual"
}
```

The exact storage location should be chosen during implementation. Candidate locations:

- `party_tracker.json` additive field such as `sceneFollowers`
- a dedicated runtime JSON file under an existing runtime-state directory

## Semantics

- A scene follower is present where state says it is present.
- A follower may move with the party if `followsParty` is true.
- A scene follower is not automatically a party NPC, PC, monster, or combatant.
- Combat validity still depends on `scene_entity_contract` or explicit combat promotion.

## Guard Integration

The location exclusivity guard should receive active follower records. If a matching anchor is an authorized follower at the current location, present-scene narration is valid. If the anchor remains bound to another location and no follower/movement state exists, current fail-closed behavior remains.

## Action Model

The implementation may add or reuse movement/update actions for scene followers. The action should be explicit and auditable.

## Rollback

Follower support can be disabled by ignoring follower records; location-bound anchor behavior remains the fallback.
