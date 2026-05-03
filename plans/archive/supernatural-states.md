# PC Supernatural States

Status: Complete
Date: 2026-05-03
Archived: 2026-05-04

Implementation: PC Supernatural State Layer (2026-05-03)
- OpenSpec change: `pc-supernatural-state-layer`
- Archived: `openspec/changes/archive/2026-05-03-pc-supernatural-state-layer/`
- Main specs synced under `openspec/specs/pc-supernatural-state-*`

See also: `openspec/specs/pc-supernatural-state-schema/spec.md` and `openspec/specs/tt-resurrection-corruption-state-action/spec.md` for final spec text.

## Purpose

Explore a safe way to represent playable supernatural PC states such as Vitreol's Voidstone corruption or a playable undead transformation without breaking the existing life/death mechanics.

## Current Status Model

PC `status` is currently a narrow life-state field, not a broad narrative-state field.

| Scope | Values | Defined / Enforced At |
| --- | --- | --- |
| PC character schema | `alive`, `dead`, `unconscious` | `schemas/char_schema.json` |
| Character normalization | `dead`, `alive`, `unconscious` | `utils/character_state_hygiene.py` |
| Encounter creatures | `alive`, `dead`, `unconscious`, `defeated` | `updates/update_encounter.py` |
| Combat prompts / validators | `alive`, `dead`, `unconscious`, `defeated` | `prompts/combat/*` |
| UI styling | `alive`, `unconscious`, `dead` | `web/templates/game_interface.html` |

Observed character-file values during exploration:

| Status | Count |
| --- | ---: |
| `alive` | 108 |
| `dead` | 6 |
| `unconscious` | 5 |

Vitreol's current PC sheet is `status: alive` in `characters/vitreol.json`. A separate monster/statblock representation exists at `modules/The_Thornwood_Watch/monsters/vitreol_corrupted_thrall.json`, but the PC sheet does not currently model that supernatural state directly.

## Recommendation

Do not use `status=corrupted` or `status=undead`.

Keep `status` as the hard life/death control field:

```json
"status": "alive"
```

Add a separate durable supernatural-state layer:

```json
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
      "Vulnerability to radiant damage",
      "Disadvantage on Wisdom saves against Voidstone influence"
    ],
    "narrativeEffects": [
      "Eyes glow with violet light",
      "Voice carries an older echo",
      "Animals and nature spirits react with fear"
    ],
    "removal": "Cleanse the Voidstone altar or complete a dedicated restoration ritual"
  }
]
```

This preserves the project principle: Python enforces reality; the LLM interprets it.

`status` remains the hard mechanical life state. `supernaturalStates` tells the UI, prompts, and validators what kind of alive thing the PC currently is.

## Why Not Expand `status`?

Using `status=corrupted` is technically possible but risky.

| System | Risk |
| --- | --- |
| Schema validation | Fails unless the enum is expanded |
| `normalize_life_state_fields()` | Positive HP currently coerces non-dead states back to `alive` |
| Combat validators | Unknown status values are rejected |
| Combat exit / initiative logic | Assumes alive/dead/unconscious/defeated semantics |
| UI | Styling exists only for alive/dead/unconscious |
| Prompts | Explicitly define `status` as life/death state |

The safe model is to split state into two axes:

```text
Life State        Supernatural State
==========        ==================
alive             voidstone_corrupted
unconscious       undead_playable
dead              abyss_marked
                  fey_bound
                  shadow_touched
```

## Existing Hook

The runtime already has a `resurrectCharacter` action in `core/ai/action_handler.py`.

Current supported modes:

```json
"mode": "ordinary_resurrection|corrupted_resurrection"
```

The current implementation persists `_supernatural_metadata`, but `schemas/char_schema.json` has `additionalProperties: false`, so this should be formalized into schema-valid fields before relying on it long term.

## Vitreol Model

Recommended Vitreol state after the Thornwood event:

| Field | Value |
| --- | --- |
| `status` | `alive` |
| `creatureTypes` | `humanoid`, optionally `undead` if the table wants the change to be biologically undead |
| `supernaturalStates[0].id` | `voidstone_corrupted` |
| `supernaturalStates[0].playable` | `true` |
| Source | Acheron's abyssal powers and the Voidstone altar |

Suggested mechanical effects:

- Resistance to necrotic damage.
- Vulnerability to radiant damage.
- Disadvantage on Wisdom saves against Voidstone influence.
- Optional: animals, nature spirits, and sacred wards react negatively.
- Optional: restorative magic works, but cleansing/restoration magic may trigger corruption checks.

Suggested narrative effects:

- Violet or abyssal light in the eyes.
- Voice sometimes carries an older echo.
- The Voidstone altar or similar corrupted anchors can pull attention or obedience.
- Natural spaces recoil or become uneasy around the character.

## Playable Undead Model

Playable undead should not use `status=dead`. They are still mechanically active.

Recommended shape:

```json
"status": "alive",
"creatureTypes": ["undead"],
"supernaturalStates": [
  {
    "id": "undead_playable",
    "label": "Playable Undead",
    "category": "undeath",
    "source": "Returned by necromantic or supernatural means",
    "playable": true,
    "mechanicalEffects": [
      "Does not need to eat, drink, or breathe",
      "May be affected differently by radiant, necrotic, healing, or turning effects"
    ],
    "narrativeEffects": [
      "Body is cold or unnaturally still",
      "Holy symbols and grave magic react strongly"
    ]
  }
]
```

Key rule: `undead` is a creature type or supernatural state, not a life-state replacement. A playable undead PC acts because `status=alive`.

## Other Fun States

| State | Gameplay Hook |
| --- | --- |
| `voidstone_corrupted` | Power at a moral cost; corruption saves/checks |
| `undead_playable` | No ordinary hunger/breathing; holy/radiant complications |
| `revenant_bound` | Cannot truly die until a vow is fulfilled |
| `abyss_marked` | Dark powers answer, but demand escalation |
| `fey_bound` | Advantage in fae/wild scenes, vulnerability to iron or oath-breaking |
| `shadow_touched` | Stealth/darkness boons, sunlight or radiant drawbacks |
| `spirit_tethered` | Can perceive ghosts, but hauntings can perceive them |
| `lycanthropic` | Strength/senses boon, control checks under moon or blood triggers |
| `time_fractured` | Occasional omen/initiative advantage, memory glitches |
| `curse_blooming` | Starts narrative-only, unlocks mechanics as it worsens |

## Implementation Shape

If this becomes an OpenSpec change, likely scope:

1. Add schema fields: `creatureTypes`, `supernaturalStates`.
2. Replace `_supernatural_metadata` with schema-valid `supernaturalStates`.
3. Update `resurrectCharacter` so `corrupted_resurrection` writes a durable state.
4. Display state badges on the Character Sheet and PDF.
5. Project supernatural states into DM Note, combat truth packs, and conversation context.
6. Keep `status` normalization unchanged.
7. Add a migration or targeted patch for Vitreol's Thornwood corruption.

## Open Questions

- Should Vitreol be `humanoid + corrupted`, or `undead + corrupted`?
- Should corruption have deterministic mechanical effects by default, or should each state carry its own explicit effect list?
- Should supernatural states have severity levels, such as `latent`, `active`, `dominant`, `cleansed`?
- Should some states be hidden from players until revealed, or always visible on the Character Sheet?
- Should `resurrectCharacter` become a broader `applySupernaturalState` action, or should resurrection remain the only way to create these states automatically?
