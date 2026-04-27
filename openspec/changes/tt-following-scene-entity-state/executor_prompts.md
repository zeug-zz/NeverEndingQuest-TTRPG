# Executor Prompts: tt-following-scene-entity-state

## Execution Contract

MUST:
- Keep following scene entities explicit and persistent.
- Preserve location exclusivity for non-following off-location anchors.
- Keep followers distinct from PCs, party NPCs, monsters, and combatants unless explicitly promoted.
- Preserve scene-entity combat validity boundaries.
- Use ASCII-only code and data.

SHOULD:
- Prefer additive state under existing runtime party/location state if it avoids new storage complexity.
- Keep follower records small and auditable.
- Implement after party-name collision and supernatural state-shape contracts are reviewed.

## Prompt 1 - State Model Decision

Implement tasks 1.1 through 1.3 only.

Allowed files:
- design/test artifacts as needed
- no broad runtime mutation until the storage decision is test-backed

Required behavior:
- Inspect existing storage patterns.
- Choose where follower state lives.
- Define minimal fields and default empty behavior.
- Add tests or source-contract assertions for the chosen schema if practical.

Verification gate:
- py_compile touched Python files
- focused tests if added

Report:
- Explain the chosen storage location and migration/default strategy.

## Prompt 2 - Follower Creation and Movement

Implement tasks 2.1 through 2.3 only.

Allowed files:
- runtime helper/action files chosen by Prompt 1
- focused tests

Required behavior:
- Create/promote a scene anchor into follower state only through explicit code path.
- Move followers with the party only when `followsParty` is true.
- Support removal/dismissal/destruction or return to location-bound state.

Forbidden scope:
- Do not implement PC resurrection.
- Do not make all anchors mobile by default.

Verification gate:
- py_compile touched Python files
- focused follower lifecycle tests

Report:
- Include example follower record before and after movement.

## Prompt 3 - Guard and Combat Validity Integration

Implement tasks 3.1 through 3.3 only.

Allowed files:
- `utils/narrator_location_exclusivity_guard.py`
- `utils/scene_entity_contract.py` if needed
- runtime callsite wiring
- focused tests

Required behavior:
- Authorized followers at current location pass location exclusivity.
- Non-following off-location anchors still fail.
- Followers are not combat-valid unless explicit combat-valid metadata/action exists.

Verification gate:
- py_compile touched Python files
- location exclusivity tests
- scene entity contract tests if touched

Report:
- Summarize pass/fail guard cases.

## Prompt 4 - Prompt Guidance and Final Verification

Implement tasks 4.1 through 5.5.

Allowed files:
- prompts and prompt tests if guidance is added
- final verification only otherwise

Required behavior:
- Teach durable followers require follower state.
- Keep dream/vision/foreshadowing no-state alternatives.

Verification gate:
- all focused follower tests
- prompt source-contract tests if prompts changed
- `openspec validate tt-following-scene-entity-state`

Report:
- Changed files, tests run, and residual risks.
