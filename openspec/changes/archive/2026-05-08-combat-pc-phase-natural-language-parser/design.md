## Context

Slash commands are efficient but tabletop facilitators naturally use prose. The goal is not to replace the combat LLM. The goal is to catch obvious, fully specified PC actions and avoid unnecessary LLM calls.

This parser should operate only during PC_PHASE and only for the currently acting PC or explicitly tagged PC. It should be conservative: uncertain means fallback.

## Contract Layer (MUST)

### Parser Scope

- Parser MUST run only during multi-PC PC_PHASE.
- Parser MUST only handle PC or allied-PC-directed actions where the acting PC is clear.
- Parser MUST require unique target resolution before applying target-specific mechanics.
- Parser MUST fall back to the full combat LLM when action facts are incomplete or ambiguous.

### Supported Initial Actions

- Parser MUST support weapon attack prose only when a d20 attack roll is supplied.
- Parser MUST support Magic Missile only when target allocation and damage amounts are explicit.
- Parser MUST support Cure Wounds or direct healing only when target and healing amount are explicit.
- Parser MUST support movement-only prose as narration-only with no mechanical file mutation.

### Mutation Authority

- Enemy HP/status changes MUST route through deterministic encounter ops or equivalent existing Python mutation helpers.
- PC/allied NPC HP, spell slot, condition, inventory, or resource changes MUST route through deterministic character ops where supported.
- Parser MUST NOT call prose updater LLMs for mechanics it claims to handle deterministically.

### Safety

- Parser MUST NOT invent missing rolls, damage, spell levels, target names, or saving throw outcomes.
- Parser MUST NOT resolve enemy or NPC saving throws unless a later explicitly scoped change adds Python save resolution.
- Parser MUST emit user-safe fallback guidance or enter existing combat LLM path on ambiguity.

## Guidance Layer (SHOULD)

### Parser Architecture

Prefer a new helper such as `utils/combat_pc_action_parser.py` with pure functions:

```python
parse_pc_phase_action(text, actor, encounter_data, party_tracker_data) -> ParseResult
```

Suggested result shape:

```python
{
    "handled": True,
    "kind": "magic_missile",
    "mechanical_feedback": "[skipTTS] Dungeon Master: ...",
    "spoken_narration": "Dungeon Master: ...",
    "character_ops": [...],
    "encounter_ops": [...],
    "ledger_event": {...},
    "fallback_reason": ""
}
```

### Conservative Pattern Matching

Use explicit patterns first:

- `roll 13`, `13 to hit`, `attack roll 13`
- `Magic Missile`, `dart`, target names, damage numbers
- `Cure Wounds`, `healing`, `heal <target> for <n>`

Do not infer complex rules from vague prose.

### Feature Flag

Add a flag such as:

```python
COMBAT_PC_PHASE_NL_FAST_PATH = False
```

Default can remain `False` for first review if parser risk is a concern. Slash-command fast path should remain independent.

## Rollback

- Disable `COMBAT_PC_PHASE_NL_FAST_PATH`.
- Keep parser tests and slash-command fast paths intact.
- Unsupported inputs continue to existing combat LLM behavior.
