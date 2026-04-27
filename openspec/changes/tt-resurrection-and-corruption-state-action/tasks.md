# Tasks

## 1. Action contract decision

- [ ] 1.1 Inspect current action and structured ops patterns.
- [ ] 1.2 Choose either a new `resurrectCharacter` action or a narrow `resurrection_apply` structured op.
- [ ] 1.3 Document the chosen shape in code comments/tests.

## 2. Runtime implementation

- [ ] 2.1 Implement explicit eligibility checks for dead characters.
- [ ] 2.2 Apply deliberate post-transition HP/status/death-save state.
- [ ] 2.3 Persist durable supernatural metadata or lifecycle history.
- [ ] 2.4 Ensure generic HP/status updates still cannot revive dead PCs.
- [ ] 2.5 Surface player-safe errors for invalid resurrection attempts.

## 3. Prompt and validation wiring

- [ ] 3.1 Add action/operation guidance to system prompts.
- [ ] 3.2 Add validation guidance for required fields and illegal generic revival.
- [ ] 3.3 Keep dream/vision/separate-entity alternatives available.

## 4. Tests

- [ ] 4.1 Add positive test for explicit ordinary resurrection.
- [ ] 4.2 Add positive test for explicit corrupted resurrection metadata.
- [ ] 4.3 Add negative test for generic HP update on dead PC.
- [ ] 4.4 Add negative test for missing source/mode.
- [ ] 4.5 Add prompt/validation source-contract tests if prompts change.

## 5. Verification

- [ ] 5.1 Run py_compile on all modified Python files.
- [ ] 5.2 Run resurrection/corruption focused tests.
- [ ] 5.3 Run dead-stickiness regression tests.
- [ ] 5.4 Run `openspec validate tt-resurrection-and-corruption-state-action`.
