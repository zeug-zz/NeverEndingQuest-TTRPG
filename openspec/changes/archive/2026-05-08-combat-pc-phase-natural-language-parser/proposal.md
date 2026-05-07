## Why

Facilitators often enter PC combat actions as natural language rather than slash commands. Some of those inputs contain complete mechanical facts, such as attack rolls, explicit Magic Missile damage allocation, or Cure Wounds healing amounts. Sending all of these through the full combat LLM and validator is slower than necessary.

The system should conservatively recognize simple complete PC actions, apply supported mechanics through deterministic Python paths, narrate locally, and fall back to the existing combat LLM when ambiguity remains.

## What Changes

- Add a conservative PC_PHASE natural-language action parser for complete, low-risk PC actions.
- Support a narrow initial set: weapon attack with supplied roll, Magic Missile with explicit dart damage, Cure Wounds/direct healing with explicit amount, and movement-only narration.
- Route supported mechanics through deterministic ops or shared Python mutation helpers without prose updater LLMs.
- Fall back to full combat LLM for ambiguous, incomplete, or complex actions.
- Record parsed actions into the PC_PHASE event ledger when available.

## Capabilities

### New Capabilities

- `tt-combat-pc-natural-action-parser`: Simple complete natural-language PC actions can be parsed and handled through deterministic PC_PHASE fast paths.

### Modified Capabilities

- `tt-combat-pc-phase-deterministic-fast-path`: Fast path extends beyond slash commands to selected complete natural-language actions.
- `tt-combat-pc-phase-event-ledger`: Parsed natural-language actions can create historical already-applied ledger entries.
- `tt-combat-structured-character-ops-routing`: Parsed PC/allied mechanics use deterministic character ops where supported.
- `tt-combat-structured-encounter-ops-routing`: Parsed enemy damage uses deterministic encounter ops or equivalent Python mutation where supported.

## Non-Goals

- Do not build a general natural-language rules engine.
- Do not parse area effects requiring enemy saves in this change.
- Do not adjudicate ambiguous advantage/disadvantage, cover, reactions, held actions, grapples, shoves, or contested checks in this change.
- Do not silently apply mechanics when target, roll, spell level, or amount is unclear.
- Do not remove the full combat LLM fallback.

## Impact

- **Affected code**: likely new parser helper, `core/managers/combat_manager.py`, `core/managers/multi_pc_combat.py`, tests.
- **Runtime behavior**: Complete simple PC action prose can resolve faster with deterministic narration.
- **Backward compatible**: Ambiguous or unsupported prose continues to existing combat LLM path.
- **Risk**: Medium-high. Parser must be conservative to avoid applying wrong mechanics.

## Fallback Strategy

Feature-flag the parser. If false positives occur, disable the parser and keep deterministic slash-command fast paths.
