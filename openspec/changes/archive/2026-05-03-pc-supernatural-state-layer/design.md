# Design: PC Supernatural State Layer

## State Model

The implementation SHOULD keep two independent axes:

```json
{
  "status": "alive",
  "creatureTypes": ["humanoid", "undead"],
  "supernaturalStates": [
    {
      "id": "voidstone_corrupted",
      "label": "Voidstone Corrupted",
      "category": "corruption",
      "source": "Acheron's abyssal power and the Voidstone altar",
      "playable": true,
      "mechanicalEffects": [
        "Resistance to necrotic damage",
        "Vulnerability to radiant damage"
      ],
      "narrativeEffects": [
        "Eyes glow with violet light"
      ],
      "removal": "Cleanse the Voidstone altar or complete a restoration ritual"
    }
  ]
}
```

Contract layer:

- `status` MUST remain the authoritative life/death state.
- `creatureTypes` MUST describe creature taxonomy, not life/death activity.
- `supernaturalStates` MUST describe durable supernatural facts, not transient mood or scene flavor.
- `mechanicalEffects` MUST NOT be silently enforced as rules-engine modifiers unless deterministic enforcement is implemented and tested.

Guidance layer:

- Existing files may omit both new fields; loaders can treat omitted `creatureTypes` as ordinary/unknown and omitted `supernaturalStates` as no durable supernatural state.
- `creatureTypes` should use normalized lowercase labels such as `humanoid`, `undead`, `construct`, `fey`, or `fiend`.
- `supernaturalStates[].id` should use stable snake_case identifiers.

## Resurrection Integration

`resurrectCharacter` already exists and supports ordinary and corrupted resurrection modes. This change SHOULD update corrupted/altered modes to write the new schema-valid state records and stop depending on private `_supernatural_metadata`.

Ordinary resurrection MAY leave `supernaturalStates` unchanged or empty unless the transition explicitly includes a supernatural consequence.

Corrupted/undead resurrection SHOULD:

- Set `status` to `alive` only through the dedicated resurrection action.
- Preserve dead-state stickiness for all generic HP/status updates.
- Add or update a `supernaturalStates` record with source and consequences.
- Add `undead` to `creatureTypes` only when the approved mode explicitly returns the PC as playable undead.

## Projection Surfaces

Projection SHOULD be concise and bounded:

- Character Sheet: display badge-like labels and creature types.
- PDF: include supernatural state summary near character profile/traits.
- DM Note: include state labels and essential mechanical/narrative effects.
- Conversation context: include one compact line per affected PC.
- Combat truth pack/context: include creature types and relevant state effects for touched combatants.

The first pass SHOULD make all durable PC supernatural states visible to players. Hidden/secret state support is intentionally excluded unless added by a later reviewed change.

## Vitreol Review Gate

Vitreol's current recommended model is either:

- `creatureTypes: ["humanoid"]` plus `voidstone_corrupted`, or
- `creatureTypes: ["humanoid", "undead"]` plus `voidstone_corrupted`.

The implementation MUST NOT silently choose between those outcomes. A targeted data patch for `characters/vitreol.json` SHOULD be prepared only after review confirms the intended table canon.

## Migration

Migration SHOULD be additive and safe:

- Existing character files without new fields remain valid or are normalized lazily only when touched by explicit repair/migration tooling.
- Existing `_supernatural_metadata` data, if present, SHOULD be converted into `supernaturalStates` by a deterministic helper or targeted migration script.
- Migration tooling MUST use atomic JSON writes.

## Rollback

Rollback can ignore `supernaturalStates` in projection surfaces while leaving data intact. Since `status` behavior is unchanged, disabling projection should restore current runtime behavior for ordinary gameplay.
