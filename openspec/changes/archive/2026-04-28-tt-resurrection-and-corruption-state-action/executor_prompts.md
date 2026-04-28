# Executor Prompts: tt-resurrection-and-corruption-state-action

## Execution Contract

MUST:
- Implement only an explicit resurrection/corruption transition path.
- Preserve dead stickiness for all generic HP/status/rest/healing paths.
- Record source, mode, consequences or supernatural metadata for non-ordinary returns.
- Reject ambiguous or incomplete resurrection attempts.
- Use ASCII-only code and prompts.

SHOULD:
- Use the new `resurrectCharacter` action (decided 2026-04-28). Do not use structured ops for resurrection.
- Keep metadata additive so older character files remain valid.
- Implement after dead stickiness and supernatural prompt contract are merged.

## Prompt 1 - Action Dispatch and Contract

Implement tasks 1.1 through 1.3 only.

Allowed files:
- `core/ai/action_handler.py`
- `prompts/system_prompt_compressed.txt`
- `prompts/system_prompt.txt`
- a new or existing focused test file under `scripts/`

Required behavior:
- Register `resurrectCharacter` in action dispatch with required parameters: `character`, `mode`, `hitPoints`, `source`.
- Add action to `@ACTIONS` block and parameters to `@PARAMS` block in system prompts.
- Lock the contract in tests with valid/invalid payload examples.
- Do not implement mutation logic yet unless needed for tests to compile.

Verification gate:
- `.venv/bin/python -m py_compile core/ai/action_handler.py`
- run focused contract tests if added

Report:
- Quote the `@ACTIONS` line and `@PARAMS` entry added to the compressed prompt.

## Prompt 2 - Runtime Transition

Implement tasks 2.1 through 2.5 only.

Allowed files:
- `core/ai/action_handler.py` — dispatch for `resurrectCharacter` action
- `updates/update_character_info.py` or a new narrow helper for post-resurrection state application
- focused tests under `scripts/`

Required behavior:
- Explicit transition can revive or corrupt only eligible dead characters.
- Generic HP/status updates remain blocked by dead stickiness.
- Death saves reset only inside this transition path.
- Corrupted/undead modes persist metadata.
- Invalid attempts return player-safe failure details.

Forbidden scope:
- Do not implement following scene entity state.
- Do not alter ordinary rest behavior.

Edit Strategy:
- Apply one anchored patch at a time; run `py_compile` before each test run.

Verification gate:
- py_compile modified Python files
- focused positive/negative resurrection tests
- dead-stickiness tests

Report:
- Include examples of accepted and rejected payloads.

## Prompt 3 - Prompt and Validation Wiring

Implement tasks 3.1 through 4.5 only.

Allowed files:
- system prompts
- validation prompts
- prompt source-contract tests

Required behavior:
- Teach the `resurrectCharacter` action only after runtime support exists.
- Validator guidance must reject missing source/mode and generic revival.
- Preserve dream/vision and separate-entity alternatives.

Verification gate:
- prompt source-contract tests
- narrator prompt validation tests if touched

Report:
- Quote the prompt guidance added for the explicit transition.

## Prompt 4 - Final Verification

Complete tasks 5.1 through 5.4.

Verification gate:
- py_compile all modified Python files
- focused resurrection/corruption tests
- dead-stickiness regression tests
- `openspec validate tt-resurrection-and-corruption-state-action`

Report:
- Summarize files, tests, and residual game-design choices.
