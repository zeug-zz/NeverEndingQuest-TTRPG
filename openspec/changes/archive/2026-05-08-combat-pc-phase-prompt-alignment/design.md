## Context

The combat audit identified prompt-level contradictions that make PC_PHASE slower and less predictable. The runtime compressed generation prompt says PC_PHASE should only resolve the active PC, but other sections still say to continue through remaining NPCs or monsters. Validation similarly carries old language about processing until the next active PC.

This change aligns prompt contracts before deeper runtime optimizations. It reduces retry loops by making the model and validator agree on the same phase model.

## Contract Layer (MUST)

### Phase Authority

- Combat generation prompt MUST state that PC_PHASE is facilitator-owned and active-PC-only.
- Combat generation prompt MUST state that ENEMY_PHASE is LLM-owned and resolves enemies plus allied NPCs in the required batch.
- PC_PHASE instructions MUST NOT direct the LLM to process enemy or allied NPC turns after a PC action.
- ENEMY_PHASE instructions MUST NOT prompt a PC for action except for valid `requestRoll` pause semantics.
- `CURRENT_PHASE` MUST be the authority when turn markers or historical recap facts are present.

### Validation Branching

- Combat validation prompt MUST evaluate PC_PHASE responses under PC_PHASE rules.
- Combat validation prompt MUST evaluate ENEMY_PHASE responses under ENEMY_PHASE batch rules.
- `requestRoll`-only PC-facing save/check/concentration responses MUST be valid if they stop after the request.
- Narration-only `[ALREADY_APPLIED]` responses MUST be valid when they do not emit duplicate mechanics.
- ENEMY_PHASE validation MUST remain strict about forbidden PC actors and required enemy/allied NPC batch handling.

### Mutation Routing

- PC and allied NPC mechanics MUST route to `updateCharacterInfo`.
- Enemy mechanics MUST route to `updateEncounter`.
- Enemy ongoing damage from spells such as Spirit Guardians MUST route to `updateEncounter`.
- Healing spells with pending healing rolls MUST still allow immediate spell slot expenditure.
- Validation prompt MUST use `at most one updateEncounter when enemy state changes exist`, not universal `exactly one updateEncounter`.

## Guidance Layer (SHOULD)

### Prompt Style

Prefer removing contradictory compatibility examples rather than adding more override text.

Compressed prompt should remain compact:

- One phase model section.
- One action routing section.
- One already-applied replay rule.
- Few examples, all aligned to the current model.

### Uncompressed Mirror

Uncompressed prompt should follow compressed runtime authority. It may contain longer explanations, but it must not preserve obsolete examples where the LLM auto-runs a PC-side full round during PC_PHASE.

## Rollback

- Prompt edits can be rolled back section-by-section if a source-contract test identifies over-tightening.
- Runtime behavior remains unchanged by this change, so rollback is prompt-only unless tests are added.
