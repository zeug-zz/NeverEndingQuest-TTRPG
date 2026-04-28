# tt-supernatural-state-shape-contract

## Why

NEQ should support vivid supernatural narration without forcing every eerie moment into durable state. The Vitreol incident showed the narrator can creatively navigate death, dreams, corruption, and false returns, but the prompt contract does not force durable supernatural claims to choose a Python state shape.

This change adds a narration contract: strange death-state narration is welcome, but if it changes durable reality it must be represented by an explicit state action or remain subjective/foreshadowing.

## What Changes

- Prompts MUST teach four valid supernatural state shapes: dead PC remains dead, separate entity, resurrected/corrupted PC, or dream/vision/echo.
- Narration MUST NOT imply ordinary healing/rest/resume state silently resurrected a dead PC.
- Durable supernatural facts MUST require explicit Python state action.
- Validation SHOULD reject or retry responses that claim durable supernatural state changes without matching actions.

## Non-Goals

- Do not implement the resurrection action in this change.
- Do not implement following scene-entity state in this change.
- Do not make the narrator timid about death, dreams, visions, corruption, or possession.

## Capabilities

- New capability: `tt-supernatural-state-shape-contract`

## Impact

Affected files likely include:
- `prompts/system_prompt_compressed.txt`
- `prompts/system_prompt.txt`
- `prompts/validation/validation_prompt_compressed.txt`
- `prompts/validation/validation_prompt.txt`
- prompt contract tests under `scripts/`

Risks:
- Overly strict prompt language could reduce creative narration. This is mitigated by explicitly allowing dreams, omens, echoes, and symbolic narration without state changes.

Fallback:
- If validator wording causes loops, keep system prompt guidance and soften validator rejection to warning/retry guidance.
