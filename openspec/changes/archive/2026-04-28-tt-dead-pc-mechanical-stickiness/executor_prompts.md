# Executor Prompts: tt-dead-pc-mechanical-stickiness

## Execution Contract

MUST:
- Implement only this change's mechanical death stickiness, rest skip, and DM Note visibility scope.
- Preserve the rule: ordinary HP writes, healing, repair, load normalization, and rest cannot revive `status: dead` or `deathSaves.failures >= 3`.
- Keep Python state as mechanical truth and leave resurrection/corruption actions to a later change.
- Use ASCII-only code/comments/output.
- Apply one anchored patch at a time in large Python files and run `py_compile` after each touched Python file.

SHOULD:
- Prefer one small helper for dead-state detection over duplicated ad hoc checks.
- Keep rest skip messaging concise and player-safe.
- Avoid broad prompt edits in this slice.

## Prompt 1 - Dead State Predicate and Hygiene

Implement tasks 1.1 through 1.5 only.

Allowed files:
- `utils/character_state_hygiene.py`
- `updates/update_character_info.py`
- `scripts/test_character_state_hygiene.py`
- narrowly related existing update-character regression tests if needed

Required behavior:
- A character with `status: dead` remains dead even if `hitPoints` is positive.
- A character with `deathSaves.failures >= 3` becomes/remains dead even if status text is stale.
- Dead normalization forces HP to 0, clears unconscious condition, and preserves at least three failed death saves.
- Living positive-HP stale-unconscious repair still sets alive and resets death saves.

Forbidden scope:
- Do not add resurrection behavior.
- Do not modify rest handling or DM Note formatting in this prompt.

Verification gate:
- `.venv/bin/python -m py_compile utils/character_state_hygiene.py updates/update_character_info.py scripts/test_character_state_hygiene.py`
- `.venv/bin/python scripts/test_character_state_hygiene.py`

Report:
- List the exact dead-state invariants covered by tests.
- Note any legacy tests updated because they assumed positive HP always means alive.

## Prompt 2 - Dead Character Rest Skip

Implement tasks 2.1 through 2.4 only.

Allowed files:
- `core/ai/action_handler.py`
- `scripts/test_rest_action.py`
- helper imports from `utils/character_state_hygiene.py` if needed

Required behavior:
- `_process_character_rest()` MUST detect dead characters immediately after load.
- Dead characters MUST be skipped before restoration action text is built.
- Skip result MUST include `skipped: true` and `skip_reason: "dead"` or equivalent structured fields.
- Dead character files MUST remain dead/0 HP/three failed saves after short or long rest.
- Alive long-rest behavior MUST remain unchanged.

Forbidden scope:
- Do not implement resurrection.
- Do not change the public rest action contract beyond additive skipped reporting.

Edit Strategy:
- Apply one anchored patch around `_process_character_rest()`, then run `py_compile` before tests.

Verification gate:
- `.venv/bin/python -m py_compile core/ai/action_handler.py scripts/test_rest_action.py`
- `.venv/bin/python scripts/test_rest_action.py`

Report:
- Include before/after summary for dead rest and alive rest cases.

## Prompt 3 - DM Note Death Visibility

Implement tasks 3.1 through 3.4 only.

Allowed files:
- `utils/multi_pc_dm_note.py`
- existing or new focused tests under `scripts/`

Required behavior:
- Full PC stats MUST show explicit dead mechanical status and death-save failures when a PC is dead.
- Condensed PC stats MUST show compact dead/dying status when relevant.
- Output MUST make DM Note truth hard to miss, for example `Status: DEAD [MECHANICAL TRUTH]`.
- Healthy living PCs SHOULD not receive noisy extra death-save lines.

Forbidden scope:
- Do not alter character loading semantics here.
- Do not add new runtime state fields.

Verification gate:
- `.venv/bin/python -m py_compile utils/multi_pc_dm_note.py`
- Run the focused DM Note test/source check added or updated by the builder.

Report:
- Paste one sample dead PC DM Note excerpt and one living PC non-regression excerpt.

## Prompt 4 - Final Verification

Complete tasks 4.1 through 4.5.

Verification gate:
- `.venv/bin/python -m py_compile utils/character_state_hygiene.py updates/update_character_info.py core/ai/action_handler.py utils/multi_pc_dm_note.py`
- `.venv/bin/python scripts/test_character_state_hygiene.py`
- `.venv/bin/python scripts/test_rest_action.py`
- any focused DM Note test added by this change
- `openspec validate tt-dead-pc-mechanical-stickiness`

Report:
- Summarize changed files, tests run, and any residual risks.
