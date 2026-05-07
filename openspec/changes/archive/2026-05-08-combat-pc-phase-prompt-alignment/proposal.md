## Why

The multi-PC combat prompts still contain legacy single-PC or model-driven initiative assumptions that conflict with the current tabletop authority model. The compressed prompt is runtime authority, and it should clearly express that the human facilitator owns PC_PHASE while the LLM resolves ENEMY_PHASE.

Prompt contradiction causes slow validation loops. A model may try to continue through NPC/enemy turns during PC_PHASE, emit actions in the wrong mutation surface, or produce a response that validation rejects even though the facilitator's intent was simple.

## What Changes

- Make compressed generation prompt define one phase contract: PC_PHASE active PC only, ENEMY_PHASE enemy/allied NPC batch only.
- Make compressed validation prompt branch by phase instead of applying full-round expectations to all responses.
- Correct known routing issues such as enemy Spirit Guardians damage and healing spell slot deferral.
- Replace universal `exactly one updateEncounter` wording with `at most one updateEncounter when enemy state changes exist`.
- Update uncompressed prompts to follow compressed runtime authority.
- Add source-contract tests so prompt drift does not reintroduce contradictions.

## Capabilities

### New Capabilities

- `tt-combat-pc-phase-prompt-contract`: Combat prompts SHALL encode the tabletop PC_PHASE/ENEMY_PHASE authority split without contradiction.

### Modified Capabilities

- `tt-combat-phase-authority-cleanup`: Phase authority is strengthened and reflected consistently in compressed and uncompressed prompts.
- `tt-combat-validation-retry-hygiene`: Validation should reject fewer valid PC_PHASE responses by using phase-specific rules.
- `tt-combat-structured-character-ops-routing`: Supported PC/allied mechanics remain routed through `updateCharacterInfo.ops`.
- `tt-combat-structured-encounter-ops-routing`: Supported enemy mechanics remain routed through `updateEncounter.ops`.

## Non-Goals

- Do not change runtime command behavior in this change.
- Do not implement deterministic command fast path in this change.
- Do not implement natural-language parser in this change.
- Do not weaken ENEMY_PHASE validation for enemy/allied NPC batch resolution.

## Impact

- **Affected files**: `prompts/combat/combat_sim_prompt_multipc_compressed.txt`, `prompts/combat/combat_validation_prompt_multipc_compressed.txt`, uncompressed mirrors, prompt/source-contract tests.
- **Runtime behavior**: LLM should produce fewer phase-inconsistent responses and fewer validation retries.
- **Backward compatible**: Existing action schemas remain unchanged.
- **Risk**: Medium. Prompt edits are high-impact and must be source-contract tested.

## Fallback Strategy

If prompt tightening causes missing narration, roll back only the specific prompt clause while preserving the phase split and routing corrections.
