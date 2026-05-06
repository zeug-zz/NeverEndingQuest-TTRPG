## 1. Combat Phase Prompt Authority Cleanup

- [x] 1.1 Make `format_pc_context_for_prompt()` emit active-PC critical override only during PC_PHASE.
- [x] 1.2 Make party turn summary suppress active-PC current-turn markers during ENEMY_PHASE.
- [x] 1.3 Make initiative/combatant marker logic suppress PC `[>] CURRENT TURN` markers during ENEMY_PHASE.
- [x] 1.4 Remove or rewrite PC_PHASE instruction blocks that direct enemy/NPC processing before the active PC.
- [x] 1.5 Update compressed and uncompressed combat generation prompts so `[>]` is PC_PHASE-only and `CURRENT_PHASE` wins.
- [x] 1.6 Update combat validation prompts so prompting PCs during ENEMY_PHASE is invalid while PC-target damage updates remain valid.

**Verification for 1.1-1.6**: `.venv/bin/python -m py_compile core/managers/multi_pc_combat.py core/managers/combat_manager.py` passes.

## 2. Deterministic Command Replay Guard

- [x] 2.1 Change `/dmg` deterministic output to include `[ALREADY_APPLIED]` and `Result HP` wording.
- [x] 2.2 Add `[ALREADY_APPLIED]` marking for resolved deterministic `/att` outcomes where mechanics are already committed.
- [x] 2.3 Add compressed and uncompressed combat prompt guidance forbidding ops for `[ALREADY_APPLIED]` results.
- [x] 2.4 Add validation or deterministic precheck logic rejecting duplicate same-target same-amount enemy HP ops after `[ALREADY_APPLIED]` damage.
- [x] 2.5 Preserve existing resume replay guard behavior in `updates/update_encounter.py`.

**Verification for 2.1-2.5**: `.venv/bin/python -m py_compile core/managers/multi_pc_combat.py utils/combat_phase_integrity_precheck.py updates/update_encounter.py` passes.

## 3. Combat Exit Post-Ops Simulation

- [x] 3.1 Add strict integer parsing for relevant proposed HP ops.
- [x] 3.2 Add conservative simulation of supported `updateEncounter.ops`: `hp_delta`, `set_hp`, and `set_status`.
- [x] 3.3 Modify combat exit guard to evaluate simulated post-response hostile state before rejecting `exit`.
- [x] 3.4 Reject exit when simulation is indeterminate and current hostiles remain.
- [x] 3.5 Add correction guidance requiring exact supported enemy HP/status ops before `exit`.

**Verification for 3.1-3.5**: `.venv/bin/python -m py_compile utils/combat_phase_integrity_precheck.py` passes.

## 4. Regression Tests

- [x] 4.1 Add tests proving ENEMY_PHASE contains no active-PC critical override.
- [x] 4.2 Add tests proving PC `[>] CURRENT TURN` markers are suppressed during ENEMY_PHASE.
- [x] 4.3 Add tests proving PC_PHASE still includes legal active-PC authority.
- [x] 4.4 Add tests proving `/dmg` logs use `[ALREADY_APPLIED]` and `Result HP`.
- [x] 4.5 Add tests proving duplicate enemy HP ops after `[ALREADY_APPLIED]` damage are rejected.
- [x] 4.6 Add tests proving distinct new damage after `[ALREADY_APPLIED]` can still be valid.
- [x] 4.7 Add tests proving `exit` is allowed when same-response ops defeat all living hostiles.
- [x] 4.8 Add tests proving `exit` is rejected when same-response ops leave hostiles alive or are malformed.

**Verification for 4.1-4.8**: `.venv/bin/python scripts/test_multi_pc_combat.py`, `.venv/bin/python scripts/test_combat_phase_integrity_precheck.py`, and `.venv/bin/python scripts/c5_regression_combat.py` pass.

## 5. Full Validation

- [x] 5.1 Run `.venv/bin/python scripts/test_update_encounter_ops_runtime.py`.
- [x] 5.2 Run `.venv/bin/python scripts/test_createencounter_failure_surfacing.py`.
- [x] 5.3 Run `openspec validate combat-phase-replay-stabilization`.
- [x] 5.4 Run targeted ASCII compliance for modified Python files or `python3 scripts/check_ascii_compliance.py --summary-only` before commit.
