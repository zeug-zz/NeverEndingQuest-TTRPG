# Tasks

## 1. Dead mechanical authority

- [ ] 1.1 Add a shared dead-state predicate in `utils/character_state_hygiene.py`.
- [ ] 1.2 Update `normalize_life_state_fields()` so explicit death or three failed death saves wins over positive HP.
- [ ] 1.3 Update `updates/update_character_info.py::_sync_death_save_state()` with the same dead-state authority.
- [ ] 1.4 Add regression coverage proving positive HP cannot revive an explicitly dead character.
- [ ] 1.5 Preserve existing stale-unconscious repair for living positive-HP characters.

## 2. Rest skip for dead characters

- [ ] 2.1 Add a dead-character guard in `_process_character_rest()` before HP/slot/feature/exhaustion restoration.
- [ ] 2.2 Return a structured skipped result with `skipped: true` and `skip_reason: "dead"`.
- [ ] 2.3 Ensure skipped dead characters do not call `update_character_info()` and do not mutate the character file.
- [ ] 2.4 Extend rest tests for long-rest dead skip and alive long-rest non-regression.

## 3. DM Note visibility

- [ ] 3.1 Add explicit `Status:` output to full PC DM Note stats when abnormal or dead.
- [ ] 3.2 Add explicit death-save output to full PC DM Note stats when death saves are relevant.
- [ ] 3.3 Add compact dead/dying status output to condensed PC stats.
- [ ] 3.4 Add or extend tests/source checks for dead status visibility.

## 4. Verification

- [ ] 4.1 Run `.venv/bin/python -m py_compile utils/character_state_hygiene.py updates/update_character_info.py core/ai/action_handler.py utils/multi_pc_dm_note.py`.
- [ ] 4.2 Run `.venv/bin/python scripts/test_character_state_hygiene.py`.
- [ ] 4.3 Run `.venv/bin/python scripts/test_rest_action.py`.
- [ ] 4.4 Run any focused DM Note regression test added by this change.
- [ ] 4.5 Run `openspec validate tt-dead-pc-mechanical-stickiness`.
