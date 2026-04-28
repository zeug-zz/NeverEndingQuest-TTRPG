# Tasks

## 1. Action contract (decided: new `resurrectCharacter` action)

- [x] 1.1 Register `resurrectCharacter` in action dispatch (`core/ai/action_handler.py`) with required parameters: `character`, `mode`, `hitPoints`, `source`.
- [x] 1.2 Add `resurrectCharacter` to `@ACTIONS` and `@PARAMS` in system prompts.
- [x] 1.3 Lock the action contract in focused tests with valid/invalid payload examples.

## 2. Runtime implementation

- [x] 2.1 Implement explicit eligibility checks for dead characters.
- [x] 2.2 Apply deliberate post-transition HP/status/death-save state.
- [x] 2.3 Persist durable supernatural metadata or lifecycle history.
- [x] 2.4 Ensure generic HP/status updates still cannot revive dead PCs.
- [x] 2.5 Surface player-safe errors for invalid resurrection attempts.

## 3. Prompt and validation wiring

- [x] 3.1 Add `resurrectCharacter` guidance to system prompts.
- [x] 3.2 Add validation guidance for required fields and illegal generic revival.
- [x] 3.3 Keep dream/vision/separate-entity alternatives available.

## 4. Tests

- [x] 4.1 Add positive test for explicit ordinary resurrection.
- [x] 4.2 Add positive test for explicit corrupted resurrection metadata.
- [x] 4.3 Add negative test for generic HP update on dead PC.
- [x] 4.4 Add negative test for missing source/mode.
- [x] 4.5 Add prompt/validation source-contract tests if prompts change.

## 5. Verification

- [x] 5.1 Run py_compile on all modified Python files.
- [x] 5.2 Run resurrection/corruption focused tests.
- [x] 5.3 Run dead-stickiness regression tests.
- [x] 5.4 Run `openspec validate tt-resurrection-and-corruption-state-action`.
