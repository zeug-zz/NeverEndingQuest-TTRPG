# Tasks

## 1. System prompt contract

- [x] 1.1 Add compressed prompt guidance for death and supernatural state shapes.
- [x] 1.2 Add full prompt guidance with examples for the four shapes.
- [x] 1.3 Include the prime directive: Python enforces reality; the DM interprets it.
- [x] 1.4 Explicitly allow dreams, visions, omens, echoes, possession, corruption, bargains, and false returns when they do not claim unsupported durable state.

## 2. Validation prompt contract

- [x] 2.1 Add validator guidance that durable supernatural state claims require matching state actions.
- [x] 2.2 Add retry guidance that preserves legal alternatives: dead PC remains dead, separate entity, corrupted resurrection action when available, or dream/vision framing.
- [x] 2.3 Avoid instructing the model to emit action names that do not exist yet.

## 3. Regression coverage

- [x] 3.1 Add prompt source-contract tests for compressed and full prompt guidance.
- [x] 3.2 Add validation prompt source-contract tests for durable-state matching-action guidance.
- [x] 3.3 Run existing narrator prompt/validation tests.

## 4. Verification

- [x] 4.1 Run `.venv/bin/python scripts/test_narrator_prompt_validation_refactor.py` or the relevant focused prompt contract tests.
- [x] 4.2 Run `.venv/bin/python scripts/test_retry_de_looping.py` if validation wording changes retry behavior.
- [x] 4.3 Run `openspec validate tt-supernatural-state-shape-contract`.
