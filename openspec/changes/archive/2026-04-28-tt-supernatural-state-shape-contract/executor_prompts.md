# Executor Prompts: tt-supernatural-state-shape-contract

## Execution Contract

MUST:
- Add prompt/validator contract only; do not implement runtime resurrection or follower state.
- Preserve vivid supernatural narration while requiring explicit state actions for durable changes.
- Include the four valid state shapes from `plans/narration-reality.md`.
- Keep compressed and uncompressed prompt guidance consistent.
- Use ASCII-only prompt text.

SHOULD:
- Keep compressed prompt additions short and directive-style.
- Use examples that clarify choices without overfitting to Vitreol only.

## Prompt 1 - System Prompt Shape Contract

Implement tasks 1.1 through 1.4 only.

Allowed files:
- `prompts/system_prompt_compressed.txt`
- `prompts/system_prompt.txt`
- focused prompt source-contract tests under `scripts/`

Required behavior:
- Add a clear contract that Python mechanical state wins for death, HP, death saves, rest, and location presence.
- Add four valid narration shapes: dead PC remains dead, separate entity, explicit corrupted/resurrected PC, dream/vision/echo.
- State that durable facts require actions; otherwise narration remains subjective or foreshadowing.
- Avoid discouraging creative horror/fantasy narration.

Forbidden scope:
- Do not add new action names to `@ACTIONS` yet.
- Do not change runtime validation code.

Verification gate:
- Run the focused prompt source-contract tests added or updated by the builder.

Report:
- Quote the compressed directive and summarize full-prompt parity.

## Prompt 2 - Validation Prompt Shape Contract

Implement tasks 2.1 through 2.3 only.

Allowed files:
- `prompts/validation/validation_prompt_compressed.txt`
- `prompts/validation/validation_prompt.txt`
- focused validation prompt tests under `scripts/`

Required behavior:
- Validation guidance MUST reject unsupported durable supernatural state changes.
- Retry guidance MUST offer legal alternatives without inventing unsupported actions.
- The validator SHOULD allow dream/vision/echo framing when no durable state is claimed.

Forbidden scope:
- Do not implement parser heuristics unless existing tests require only source-contract checks.
- Do not add resurrection runtime behavior.

Verification gate:
- `.venv/bin/python scripts/test_narrator_prompt_validation_refactor.py`
- `.venv/bin/python scripts/test_retry_de_looping.py` if touched assertions cover retry wording

Report:
- Summarize legal retry alternatives taught to the validator.

## Prompt 3 - Final Verification

Complete tasks 3.1 through 4.3.

Verification gate:
- focused prompt contract tests
- `.venv/bin/python scripts/test_narrator_prompt_validation_refactor.py`
- `.venv/bin/python scripts/test_retry_de_looping.py` if validation retry language changed
- `openspec validate tt-supernatural-state-shape-contract`

Report:
- Changed files, tests run, and residual risk around prompt strictness.
