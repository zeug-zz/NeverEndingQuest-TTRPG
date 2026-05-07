## Builder Prompt: Combat PC Phase Contract Closure

Implement `openspec/changes/combat-pc-phase-contract-closure` exactly as a narrow audit-closure pass. Do not add new combat features. Do not enable the natural-language parser by default.

### MUST Fix Runtime Safety

1. In `core/managers/combat_manager.py`, gate the natural-language parser block with `COMBAT_PC_PHASE_NL_FAST_PATH`.
2. Preserve the existing fallback path when the flag is `False` or when `parse_pc_phase_action(...)` returns `handled=False`.
3. In `core/managers/multi_pc_combat.py`, ensure `handle_combat_command(...)` returns four values on every path. The unsupported-command path must be `(None, None, None, False)`.
4. Reorder parser integration so state mutations happen before printing mechanical feedback, spoken narration, or appending `[ALREADY_APPLIED]` history.
5. Change `utils/combat_pc_action_parser.py` application behavior so failed `update_encounter(...)` or `update_character_info(...)` calls return failure instead of logging and continuing as success.
6. Do not record PC_PHASE ledger events for parser results unless all required mutations succeeded.

### MUST Harden Parser Authority

1. Magic Missile fast path must not apply damage unless caster slot availability or a valid casting source is proven.
2. If slot availability cannot be proven, Magic Missile must fall back or emit safe guidance without mutation.
3. Healing fast path must load authoritative character state for PC/allied NPC targets before accepting ordinary healing.
4. Ordinary healing must not heal a mechanically dead PC or clear death state.
5. Healing spell slot spend must only be claimed if the slot spend succeeds or availability is proven.
6. Add parser tests for slot spend success, unavailable slot fallback, and dead-target healing fallback.

### MUST Fix Prompt Drift

1. In `prompts/combat/combat_sim_prompt_multipc_compressed.txt`, remove the PC_PHASE contradiction: do not say PC action resolution continues into remaining NPCs/monsters.
2. Replace universal `EXACTLY ONE updateEncounter` wording with conditional `at most one updateEncounter when enemy state changes exist`.
3. In `prompts/combat/combat_validation_prompt_multipc_compressed.txt`, remove or qualify universal exact-one language while preserving validation examples for multiple updateEncounter violations.
4. Mirror any necessary parity updates into uncompressed combat prompts.

### MUST Add Tests

1. Add source-contract tests rejecting:
   - `continue processing remaining NPCs/monsters`
   - universal `EXACTLY ONE updateEncounter per response consolidating ALL enemy changes`
   - universal `System requires exactly ONE` when not scoped to an example
2. Add runtime/source tests proving parser invocation checks `COMBAT_PC_PHASE_NL_FAST_PATH`.
3. Add unit tests proving unhandled `handle_combat_command(...)` return shape is four values.
4. Add parser apply failure tests proving no `[ALREADY_APPLIED]` history/ledger/feedback is emitted on failed mutation.

### Verification Commands

Run these before marking tasks complete:

```bash
.venv/bin/python -m py_compile model_config.py utils/combat_pc_action_parser.py core/managers/combat_manager.py core/managers/multi_pc_combat.py scripts/test_combat_pc_action_parser.py scripts/c5_regression_combat.py scripts/test_multi_pc_combat.py scripts/test_combat_state_coherence_repair.py scripts/test_gpt54_chat_params_contract.py
.venv/bin/python scripts/test_combat_pc_action_parser.py
.venv/bin/python scripts/test_multi_pc_combat.py
.venv/bin/python scripts/c5_regression_combat.py
.venv/bin/python scripts/test_combat_state_coherence_repair.py
.venv/bin/python scripts/test_gpt54_chat_params_contract.py
openspec validate combat-pc-phase-contract-closure
openspec validate combat-pc-phase-prompt-alignment
openspec validate combat-pc-phase-action-ledger
openspec validate combat-pc-phase-fast-path
openspec validate combat-pc-phase-natural-language-parser
openspec validate tt-deterministic-combat-death-saves
```

### Stop Conditions

Stop and report if any proposed parser hardening requires a general natural-language rules engine, expanded spell support, or enabling the parser by default. Those are explicitly out of scope.
