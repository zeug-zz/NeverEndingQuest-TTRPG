# Executor Prompts: tt-following-scene-entity-state

## Execution Contract

MUST:
- Keep following scene entities explicit and persistent.
- Preserve location exclusivity for non-following off-location anchors.
- Keep followers distinct from PCs, party NPCs, monsters, and combatants unless explicitly promoted.
- Preserve scene-entity combat validity boundaries.
- Use ASCII-only code and data.

SHOULD:
- Keep follower records small and auditable in dedicated `data/runtime/scene_followers.json`.
- Implement after party-name collision and supernatural state-shape contracts are reviewed.

## Prompt 1 - Follower State Storage and Schema

Implement tasks 1.1 through 1.3 only.

Storage decision is LOCKED: `data/runtime/scene_followers.json` (dedicated file, not party_tracker.json).

Allowed files:
- `data/runtime/scene_followers.json` (new file)
- load/save helper module (new or in existing utility)
- focused test script

Required behavior:
- Implement load/save helper with safe_read_json / safe_write_json atomic operations.
- Define minimal follower schema: `entity_id`, `source_location`, `follows_party` (bool), `scene_entity_metadata` (optional dict), `created_at`.
- Empty-default behavior: if file missing or empty, return empty dict/list with no errors.
- Add schema test asserting required fields present on follower records.

Verification gate:
- py_compile touched Python files
- focused schema and load/save tests

Report:
- List helper module path, schema fields, and empty-default behavior confirmation.

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
