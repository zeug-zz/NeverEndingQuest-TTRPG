## 1. Death-Save State Helpers

- [x] 1.1 Add a deterministic helper on `MultiPCCombatManager` or `CombatStateManager` to identify all unstable 0-HP PCs with unresolved death-save obligations for the current PC phase.
- [x] 1.2 Add a parser for death-save roll input accepting `3`, `I roll 3`, `roll 3`, `/death 3`, and `/ds 3` only while a deterministic death-save gate is active.
- [x] 1.3 Add a resolver that applies `PCCombatState.apply_death_save(roll)` and returns a user-facing result message.
- [x] 1.4 Add in-memory per-PC-phase cadence tracking so a resolved death save is not requested twice in the same PC phase.
- [x] 1.5 Ensure healing above `0 HP` clears death-save counters and cadence state.

**Verification for 1.1-1.5**: `.venv/bin/python -m py_compile core/managers/multi_pc_combat.py` passes.

## 2. Deterministic Persistence

- [x] 2.1 Persist failed and successful death-save counters immediately after a resolved roll.
- [x] 2.2 Persist natural `20` recovery as HP `1`, alive state, and cleared death saves.
- [x] 2.3 Persist three failures as mechanical death.
- [x] 2.4 Persist three successes as schema-valid unconscious/stable-equivalent character JSON without writing `status: stable`.
- [x] 2.5 Surface a user-safe system error if persistence fails rather than silently continuing.

**Verification for 2.1-2.5**: `.venv/bin/python -m py_compile core/managers/multi_pc_combat.py updates/update_character_info.py` passes if both are modified; otherwise compile the touched subset.

## 3. Combat Loop Input Gate

- [x] 3.1 In `core/managers/combat_manager.py`, emit deterministic DM-continuity prompts through the normal `Dungeon Master:` output path at PC phase start for unstable 0-HP PCs that must roll death saves.
- [x] 3.2 Ensure death-save request prompts are eligible for DM voice/TTS and do not include `[skipTTS]` or `[SYSTEM]` markers.
- [x] 3.3 Route valid death-save roll input to Python resolver before fast-lane command handling and before LLM calls.
- [x] 3.4 Keep invalid death-save input gated with `[skipTTS]` system-style guidance and no LLM call.
- [x] 3.5 Block `/att`, `/dmg`, `/end`, and normal action commands with `[skipTTS]` system-style guidance while any current PC-phase death-save obligation is unresolved.
- [x] 3.6 After successful death-save resolution, mark that PC's PC-phase death-save obligation complete without forcing enemy phase prematurely.
- [x] 3.7 Preserve existing behavior for other alive PCs and enemy/NPC batch phase.

**Verification for 3.1-3.7**: `.venv/bin/python -m py_compile core/managers/combat_manager.py core/managers/multi_pc_combat.py` passes.

## 4. Prompt Contract Alignment

- [x] 4.1 Add minimal combat prompt guidance that death-save rolls are Python-deterministic and must not be invented or persisted by the LLM.
- [x] 4.2 Add minimal validation prompt guidance that a Python-handled death-save result marked as already applied must not be duplicated through LLM ops.
- [x] 4.3 Keep prompt changes minimal and ASCII-only.

**Verification for 4.1-4.3**: Source-contract tests or grep checks prove the guidance exists in compressed combat prompt/validation prompt files if modified.

## 5. Regression Tests

- [x] 5.1 Extend `scripts/test_multi_pc_combat.py` for roll parsing forms and invalid roll rejection.
- [x] 5.2 Extend `scripts/test_multi_pc_combat.py` for natural 1, normal failure, normal success, natural 20, three failures, and three successes.
- [x] 5.3 Add tests proving stable persistence does not write `status: stable` to character JSON.
- [x] 5.4 Add tests proving a resolved death save is not requested twice in the same PC phase.
- [x] 5.5 Add tests proving the same incapacitated PC is prompted again on the next PC phase if still unstable at 0 HP.
- [x] 5.6 Add or extend `scripts/c5_regression_combat.py` source/behavior checks for the combat-loop gate ordering before LLM generation.
- [x] 5.7 Add tests proving the death-save request prompt is normal DM output without `[skipTTS]` or `[SYSTEM]`, while invalid input and blocked commands use `[skipTTS]` system-style guidance.
- [x] 5.8 Add tests proving normal commands and `/end` remain blocked while current PC-phase death-save obligations are unresolved and unchanged after obligations are resolved.

**Verification for 5.1-5.8**: `.venv/bin/python scripts/test_multi_pc_combat.py` and `.venv/bin/python scripts/c5_regression_combat.py` pass.

## 6. Full Validation

- [x] 6.1 Run `.venv/bin/python -m py_compile core/managers/multi_pc_combat.py core/managers/combat_manager.py` plus any other modified Python files.
- [x] 6.2 Run `.venv/bin/python scripts/test_multi_pc_combat.py`.
- [x] 6.3 Run `.venv/bin/python scripts/c5_regression_combat.py`.
- [x] 6.4 Run `openspec validate tt-deterministic-combat-death-saves`.
- [x] 6.5 Run targeted ASCII compliance for modified Python files or `python3 scripts/check_ascii_compliance.py --summary-only` before commit.
